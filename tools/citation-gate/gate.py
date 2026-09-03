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

from lib.citation import find_malformed, parse_all, render_clean  # noqa: E402
from lib.corpus import Corpus  # noqa: E402

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


def section_bodies(text: str) -> list[tuple[str, str]]:
    """تقطيع الوثيقة إلى (عنوان، متن) حسب العناوين."""
    heads = list(re.finditer(r"^\s{0,3}#{1,4}\s*(.+)$", text, re.MULTILINE))
    out = []
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append((h.group(0), text[h.end():end]))
    return out


def check(path: Path, kind: str, db: str, cfg: dict) -> dict:
    text = path.read_text(encoding="utf-8")
    rules = cfg.get("citations", {})
    min_needed = int(rules.get(f"min_citations_{kind}", 0) or 0)

    problems: list[str] = []
    resolved: list[dict] = []

    # ── 1. علامات مشوّهة — أرجح أشكال الاستشهاد الملفَّق ──
    for pos, raw in find_malformed(text):
        line = text.count("\n", 0, pos) + 1
        problems.append(f"سطر {line}: علامة استشهاد مشوّهة «{raw}» — لا تطابق القواعد")

    # ── 2. حل كل علامة صحيحة مقابل المدونة ──
    cits = parse_all(text)
    corpus = Corpus(db)
    for c in cits:
        line = text.count("\n", 0, c.pos) + 1
        ok, why = corpus.resolve(c.instrument_id, c.article_key)
        if ok:
            inst = corpus.instrument(c.instrument_id)
            resolved.append({"marker": c.raw, "ref": c.ref_id,
                             "instrument": inst["title"], "line": line})
        else:
            problems.append(f"سطر {line}: {why}  ← {c.raw}")

    # ── 3. حد أدنى من الإسناد ──
    if len(resolved) < min_needed:
        problems.append(
            f"عدد الإسنادات المُحلّة {len(resolved)} أقل من الحد الأدنى {min_needed} "
            f"لهذا النوع من الوثائق")

    # ── 4. أقسام قانونية بلا سند ──
    for head, body in section_bodies(text):
        if LEGAL_SECTION_RE.match(head) and body.strip() and not parse_all(body):
            title = head.strip("# ").strip()
            problems.append(f"القسم «{title}» يعرض حجة قانونية بلا أي إسناد")

    corpus.close()
    return {
        "file": str(path), "kind": kind,
        "passed": not problems,
        "citations_resolved": len(resolved),
        "citations_total": len(cits),
        "resolved": resolved,
        "problems": problems,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="بوابة التحقق من الإسناد القانوني")
    ap.add_argument("file", type=Path)
    ap.add_argument("--kind", choices=["memo", "pleading", "opinion"], default="memo",
                    help="memo=مذكرة  pleading=مرافعة  opinion=رأي")
    ap.add_argument("--db", default=str(ROOT / "corpus/index/corpus.db"))
    ap.add_argument("--render", type=Path, metavar="OUT",
                    help="عند النجاح: كتابة الوثيقة النهائية بلا علامات آلية")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.file.exists():
        print(f"الملف غير موجود: {args.file}", file=sys.stderr)
        return 2
    cfg = load_office_config()
    try:
        report = check(args.file, args.kind, args.db, cfg)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"\n══ بوابة الإسناد — {args.file.name} ══")
        print(f"{C_D}النوع: {args.kind}   الإسنادات: "
              f"{report['citations_resolved']}/{report['citations_total']} مُحلّة{C_0}\n")
        for r in report["resolved"]:
            print(f"  {C_G}✓{C_0} سطر {r['line']}: {r['ref']} — {r['instrument']}")
        for p in report["problems"]:
            print(f"  {C_R}✗{C_0} {p}")
        print()
        if report["passed"]:
            print(f"{C_G}✓ قُبلت المسودة — كل إسناد يُحل إلى المدونة المحلية.{C_0}\n")
        else:
            print(f"{C_R}✗ رُفضت المسودة — {len(report['problems'])} مشكلة إسناد.{C_0}")
            print(f"{C_D}  أعد الملف إلى مرحلة الصياغة. لا تُصحَّح الإسنادات بالتخمين:\n"
                  f"    python3 tools/corpus/corpus_cli.py search \"<الموضوع>\"{C_0}\n")

    if report["passed"] and args.render:
        args.render.parent.mkdir(parents=True, exist_ok=True)
        args.render.write_text(render_clean(args.file.read_text(encoding="utf-8")),
                               encoding="utf-8")
        if not args.json:
            print(f"{C_D}الوثيقة النهائية: {args.render}{C_0}\n")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
