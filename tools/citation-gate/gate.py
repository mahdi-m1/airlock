#!/usr/bin/env python3
"""بوابة الإسناد — الحاجز بين المكتب والهلوسة القانونية.

The citation gate. Every memorandum and pleading passes through this before it
can leave the drafting stage. It is deterministic: no model judges a citation.

القاعدة: كل إشارة قانونية في المسودة يجب أن تحمل علامة آلية تُحل إلى مادة
موجودة فعلًا في المدونة المحلية المُتحقق منها. إسناد لا يُحل ⇒ المسودة مرفوضة
وتعود لمرحلة الصياغة. هذا ما يجعل مخرجات المكتب قابلة للتحقق لا مجرد نص مقنع.

    gate.py مسودة.md --kind memo
    gate.py مسودة.md --kind pleading --json
    gate.py مسودة.md --render وثيقة-نهائية.md    # ينظّف العلامات بعد النجاح
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import yaml  # noqa: E402

from lib import calibrate as cal  # noqa: E402
from lib import semantic  # noqa: E402
from lib.citation import find_malformed, parse_all, render_clean  # noqa: E402
from lib.corpus import Corpus, amendment_warning  # noqa: E402

C_R, C_G, C_Y, C_D, C_0 = "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"

# العناوين التي يجب أن تحوي إسنادًا — قسم قانوني بلا سند هو العطب الأخطر
LEGAL_SECTION_RE = re.compile(
    r"^\s{0,3}#{1,4}\s*.*(الأسانيد|السند القانوني|التكييف|النصوص|الأساس القانوني"
    r"|المرافعة|الدفوع|أسباب)", re.MULTILINE)


def load_office_config() -> dict:
    p = ROOT / "config/office.yaml"
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


DEFAULT_OVERLAP = 0.35
CALIBRATION = ROOT / "corpus/index/calibration.json"


def resolve_threshold(rules: dict) -> tuple[float, str]:
    """عتبة التداخل: مُعايَرة من المدونة إن أمكن، وإلا القيمة الثابتة.

    `auto` يجعل العتبة ترتفع تلقائيًا كلما كبرت المدونة، بقيمة مقيسة من
    المدونة نفسها بدل رقم مُخمَّن — ودون أن يعتمد ذلك على تذكّر أحد.
    """
    raw = rules.get("min_semantic_overlap", DEFAULT_OVERLAP)
    if isinstance(raw, str) and raw.strip().lower() == "auto":
        if (t := cal.load(CALIBRATION)) is not None:
            return t, "مُعايَرة"
        return DEFAULT_OVERLAP, "افتراضية (لم تُعاير بعد)"
    try:
        return float(raw), "ثابتة"
    except (TypeError, ValueError):
        return DEFAULT_OVERLAP, "افتراضية"


def section_bodies(text: str) -> list[tuple[str, str]]:
    """تقطيع الوثيقة إلى (عنوان، متن) حسب العناوين."""
    heads = list(re.finditer(r"^\s{0,3}#{1,4}\s*(.+)$", text, re.MULTILINE))
    out = []
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append((h.group(0), text[h.end():end]))
    return out


def check(path: Path, kind: str, db: str, cfg: dict, *, deep: bool = True) -> dict:
    text = path.read_text(encoding="utf-8")
    rules = cfg.get("citations", {})
    min_needed = int(rules.get(f"min_citations_{kind}", 0) or 0)
    min_overlap, overlap_src = resolve_threshold(rules)

    problems: list[str] = []
    resolved: list[dict] = []
    adjudicate: list[dict] = []
    amendment_notes: list[str] = []
    warned: set[str] = set()

    # ── 1. علامات مشوّهة — أرجح أشكال الاستشهاد الملفَّق ──
    for pos, raw in find_malformed(text):
        line = text.count("\n", 0, pos) + 1
        problems.append(f"سطر {line}: علامة استشهاد مشوّهة «{raw}» — لا تطابق القواعد")

    # ── 2. حل كل علامة صحيحة مقابل المدونة ──
    cits = parse_all(text)
    spans = [(c.pos, len(c.raw)) for c in cits]
    corpus = Corpus(db)
    idf = corpus.term_idf() if deep else {}
    for c in cits:
        line = text.count("\n", 0, c.pos) + 1
        ok, why = corpus.resolve(c.instrument_id, c.article_key)
        if not ok:
            problems.append(f"سطر {line}: {why}  ← {c.raw}")
            continue
        inst = corpus.instrument(c.instrument_id)
        entry = {"marker": c.raw, "ref": c.ref_id,
                 "instrument": inst["title"], "line": line}
        if note := amendment_warning(inst):
            entry["amendment_note"] = note
            # تنبيه واحد لكل تشريع: تكراره مع كل استشهاد ضجيج يُخفي غيره
            if c.instrument_id not in warned:
                warned.add(c.instrument_id)
                amendment_notes.append(f"{inst['title']}: {note}")

        # ── 2ب. التدقيق الدلالي: هل تقول المادة ما نُسب إليها؟ ──
        art = corpus.article(c.instrument_id, c.article_key) if c.article_key else None
        if deep and art is not None:
            claim = semantic.claim_span(text, c.pos, len(c.raw), spans)
            sup = semantic.check(claim, art["text"], idf=idf, min_overlap=min_overlap)
            entry |= {"verdict": sup.verdict, "overlap": round(sup.overlap, 3)}
            if sup.blocking:
                for m in sup.conflicts:
                    problems.append(f"سطر {line}: {m}  ← {c.raw}")
                continue
            if sup.verdict == "يحتاج تحكيمًا":
                adjudicate.append(entry | {
                    "claim": claim, "article_label": art["label"],
                    "article_text": art["text"], "doubts": sup.doubts})
        resolved.append(entry)

    # ── 3. حد أدنى من الإسناد ──
    if len(resolved) < min_needed:
        problems.append(
            f"عدد الإسنادات المُحلّة {len(resolved)} أقل من الحد الأدنى {min_needed} "
            f"لهذا النوع من الوثائق")

    # ── 4. أقسام قانونية بلا سند ──
    # لا تسري على العقود: بنودها التزامات لا حجج، وإلزامها بإسناد يحوّل العقد
    # إلى مذكرة. اكتمالها يفحصه tools/contracts/check_clauses.py.
    for head, body in ([] if kind == "contract" else section_bodies(text)):
        if LEGAL_SECTION_RE.match(head) and body.strip() and not parse_all(body):
            title = head.strip("# ").strip()
            problems.append(f"القسم «{title}» يعرض حجة قانونية بلا أي إسناد")

    corpus.close()
    return {
        "file": str(path), "kind": kind,
        "passed": not problems,
        "overlap_threshold": min_overlap,
        "overlap_threshold_source": overlap_src,
        "needs_adjudication": bool(adjudicate),
        "citations_resolved": len(resolved),
        "citations_total": len(cits),
        "resolved": resolved,
        "adjudicate": adjudicate,
        "problems": problems,
        "amendment_notes": amendment_notes,
    }


WORKSHEET_HEADER = """# ورقة التحكيم الدلالي

بوابة الإسناد أثبتت أن كل مادة أدناه **موجودة** في المدونة. ما لم تثبته — ولا
يمكن إثباته آليًا — هو أن المادة تقول فعلًا ما نُسب إليها. هذا العطب هو الوحيد
الذي يعبر البوابة الحتمية، ولذلك يُحسم هنا بندًا بندًا لا بانطباع عام.

**لكل بند اكتب حكمًا واحدًا من ثلاثة:**

- `مسنود` — نص المادة يحمل ما نُسب إليه. اذكر العبارة الحاملة له من المادة.
- `جزئي` — يسنده في شق دون شق. بيّن الشق غير المسنود وما يلزم لتصحيحه.
- `غير مسنود` — لا يحمله. المسودة تُرد للصياغة.

لا تترك بندًا بلا حكم، ولا تكتب «يبدو صحيحًا». إن لم تجد العبارة الحاملة في
نص المادة أدناه فالحكم `غير مسنود` — النص المعروض هو كل ما في المدونة.
"""


def write_worksheet(report: dict, path: Path) -> None:
    """ورقة تحكيم مهيكلة للبنود الملتبسة وحدها.

    Only ambiguous citations reach here, so the adjudicating agent reads a
    handful of short items instead of the whole draft — the judgement is
    recorded per citation and auditable, and the token cost stays proportional
    to genuine doubt rather than to document length.
    """
    lines = [WORKSHEET_HEADER, f"\n**الوثيقة:** `{report['file']}`  ",
             f"**بنود تحتاج تحكيمًا:** {len(report['adjudicate'])}\n\n---\n"]
    for i, a in enumerate(report["adjudicate"], 1):
        lines.append(f"\n## {i}. {a['ref']} — {a['article_label']} من {a['instrument']}\n")
        lines.append(f"**ما نسبته المسودة إليها** (سطر {a['line']}):\n\n"
                     f"> {a['claim']}\n")
        lines.append(f"**نص المادة كما في المدونة:**\n\n> {a['article_text']}\n")
        lines.append("**ما استوقف الفحص الآلي:**\n")
        lines += [f"- {d}" for d in a["doubts"]]
        lines.append(f"\n**الحكم:** <!-- مسنود | جزئي | غير مسنود -->\n")
        lines.append("**العبارة الحاملة من نص المادة:**\n")
        lines.append("**التعليل:**\n\n---\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="بوابة التحقق من الإسناد القانوني — وجود المادة ثم دلالتها")
    ap.add_argument("file", type=Path)
    ap.add_argument("--kind", choices=["memo", "pleading", "opinion", "contract"], default="memo",
                    help="memo=مذكرة  pleading=مرافعة  opinion=استشارة  contract=عقد")
    ap.add_argument("--db", default=str(ROOT / "corpus/index/corpus.db"))
    ap.add_argument("--render", type=Path, metavar="OUT",
                    help="عند النجاح: كتابة الوثيقة النهائية بلا علامات آلية")
    ap.add_argument("--worksheet", type=Path, metavar="OUT",
                    help="كتابة ورقة التحكيم للبنود الملتبسة")
    ap.add_argument("--no-semantic", action="store_true",
                    help="الاكتفاء بفحص الوجود دون التدقيق الدلالي")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.file.exists():
        print(f"الملف غير موجود: {args.file}", file=sys.stderr)
        return 2
    cfg = load_office_config()
    try:
        report = check(args.file, args.kind, args.db, cfg, deep=not args.no_semantic)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    pending = report["passed"] and report["needs_adjudication"]

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"\n══ بوابة الإسناد — {args.file.name} ══")
        mode = "وجود + دلالة" if not args.no_semantic else "وجود فقط"
        thr = ("   عتبة الدلالة: "
               f"{report['overlap_threshold']:g} ({report['overlap_threshold_source']})"
               if not args.no_semantic else "")
        print(f"{C_D}النوع: {args.kind}   الفحص: {mode}   الإسنادات: "
              f"{report['citations_resolved']}/{report['citations_total']} مُحلّة"
              f"{thr}{C_0}\n")
        for r in report["resolved"]:
            v = r.get("verdict")
            mark, col = (f"?", C_Y) if v == "يحتاج تحكيمًا" else ("✓", C_G)
            extra = ""
            if v:
                extra = f"  {C_D}[{v}"
                extra += f"، تداخل {r['overlap']:.0%}]{C_0}" if "overlap" in r else f"]{C_0}"
            print(f"  {col}{mark}{C_0} سطر {r['line']}: {r['ref']} — {r['instrument']}{extra}")
        for n in report["amendment_notes"]:
            print(f"  {C_Y}⚠{C_0} {n}")
        for a in report["adjudicate"]:
            for d in a["doubts"]:
                print(f"      {C_Y}?{C_0} {d}")
        for p in report["problems"]:
            print(f"  {C_R}✗{C_0} {p}")
        print()
        if not report["passed"]:
            print(f"{C_R}✗ رُفضت المسودة — {len(report['problems'])} مشكلة إسناد.{C_0}")
            print(f"{C_D}  أعد الملف إلى مرحلة الصياغة. لا تُصحَّح الإسنادات بالتخمين:\n"
                  f"    python3 tools/corpus/corpus_cli.py search \"<الموضوع>\"{C_0}\n")
        elif pending:
            n = len(report["adjudicate"])
            print(f"{C_Y}⏳ اجتاز فحص الوجود، و{n} إسناد يحتاج تحكيمًا دلاليًا.{C_0}")
            print(f"{C_D}  المادة موجودة، لكن كونها تقول ما نُسب إليها لم يثبت آليًا.\n"
                  f"  لا تُسلَّم الوثيقة قبل حسم هذه البنود.{C_0}\n")
        elif report["amendment_notes"]:
            print(f"{C_G}✓ قُبلت المسودة{C_0} — كل إسناد يُحل ودلالته مسنودة، "
                  f"{C_Y}مع تنبيه تعديلات.{C_0}")
            print(f"{C_D}  المادة موجودة ونصها مطابق لما استُورد، لكنه النص الأصلي\n"
                  f"  لا النافذ. راجع أثر التعديلات قبل الاعتماد.{C_0}\n")
        else:
            print(f"{C_G}✓ قُبلت المسودة — كل إسناد يُحل، ودلالته مسنودة.{C_0}\n")

    if args.worksheet and report["adjudicate"]:
        write_worksheet(report, args.worksheet)
        if not args.json:
            print(f"{C_D}ورقة التحكيم: {args.worksheet}{C_0}\n")

    # الوثيقة النهائية لا تُنتج ما دام هناك إسناد لم يُحسم.
    if report["passed"] and not pending and args.render:
        args.render.parent.mkdir(parents=True, exist_ok=True)
        args.render.write_text(render_clean(args.file.read_text(encoding="utf-8")),
                               encoding="utf-8")
        if not args.json:
            print(f"{C_D}الوثيقة النهائية: {args.render}{C_0}\n")

    # 0 مقبولة · 1 مرفوضة · 3 تحتاج تحكيمًا — ليميّزها الخط
    return 0 if report["passed"] and not pending else (3 if pending else 1)


if __name__ == "__main__":
    sys.exit(main())
