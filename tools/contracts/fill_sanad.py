#!/usr/bin/env python3
"""ملء حقول السند في قوائم البنود من المدونة المحلية.

Fills the `sanad` fields in `config/clauses.yaml` from the corpus — the step
that turns the clause checker from an adviser into an enforcer. A statutory
clause rule is only enforced once its basis resolves to a verified article.

الأداة **تقترح ولا تملأ**. مطابقة البحث ليست صحةً قانونية: أقرب مادة نصًا قد
لا تكون الحاكمة، والاعتماد على أول نتيجة هنا هو نفس عطب الإسناد الذي يمر على
البوابة لأن رقمه صحيح ومضمونه لا يسند الحجة. لذلك تكتب الأداة ورقة مراجعة
يحسمها أمين المصادر بندًا بندًا، ثم تُطبَّق اختياراته.

    fill_sanad.py                          # اقتراح مرشّحات → ورقة مراجعة
    fill_sanad.py --apply murajaa.md       # تطبيق ما اعتُمد
    fill_sanad.py --status                 # ما المُسنَد وما الناقص
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import yaml  # noqa: E402

from lib.citation import parse_all  # noqa: E402
from lib.corpus import Corpus  # noqa: E402

C_R, C_G, C_Y, C_D, C_0 = "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"
CLAUSES = ROOT / "config/clauses.yaml"
DEFAULT_SHEET = ROOT / "corpus/index/sanad-review.md"

HEADER = """# ورقة اعتماد أسناد بنود العقود

لكل بند أدناه مرشّحات من المدونة المحلية. **اكتب علامة المادة المعتمدة في سطر
«المعتمد»** أو اتركه فارغًا إن لم يكن فيها ما يصلح.

قواعد الاعتماد:

- اقرأ نص المادة، لا عنوانها. المطلوب أن **تحمل المادة القاعدة** التي يفرضها
  البند، لا أن تشترك معه في ألفاظ.
- مادة قريبة في الموضوع وبعيدة في الحكم = **لا تُعتمد**. تركُ الحقل فارغًا يُبقي
  البند تنبيهًا يدويًا، وهو أسلم من فرض قاعدة على عقود العملاء بسند خاطئ.
- إن لم تجد المرشّح الصحيح فابحث بنفسك ثم اكتب علامته:
  `python3 tools/corpus/corpus_cli.py search "<الموضوع>" --area <النطاق>`

ثم طبّق: `python3 tools/contracts/fill_sanad.py --apply <هذا الملف>`

---
"""


def load_text() -> str:
    return CLAUSES.read_text(encoding="utf-8")


def statutory_items(cfg: dict) -> list[dict]:
    """كل بند قانوني مع موقعه في القوائم."""
    out = []
    for tkey, spec in cfg.get("types", {}).items():
        for group in ("required", "void"):
            for item in spec.get(group, []):
                if item.get("basis") == "statutory":
                    out.append({"type": tkey, "type_name": spec.get("name", tkey),
                                "group": group, "area": spec.get("practice_area"),
                                **item})
    return out


def cmd_status(cfg: dict, db: str) -> int:
    items = statutory_items(cfg)
    print("\n══ حالة أسناد بنود العقود ══\n")
    corpus = None
    try:
        corpus = Corpus(db)
    except FileNotFoundError:
        print(f"{C_Y}  المدونة غير مبنية — لا يمكن التحقق من الأسناد الموجودة.{C_0}\n")

    filled = broken = empty = 0
    for it in items:
        sanad = (it.get("sanad") or "").strip()
        tag = f"{it['type']}/{it['key']}"
        if not sanad:
            empty += 1
            print(f"  {C_Y}·{C_0} {tag:<28} بلا سند — يُرصد ولا يُفرض")
            continue
        if corpus is None:
            print(f"  {C_D}?{C_0} {tag:<28} {sanad}")
            continue
        cits = parse_all(sanad)
        if not cits:
            broken += 1
            print(f"  {C_R}✗{C_0} {tag:<28} علامة غير صالحة نحويًا: {sanad}")
            continue
        ok, why = corpus.resolve(cits[0].instrument_id, cits[0].article_key)
        if ok:
            filled += 1
            print(f"  {C_G}✓{C_0} {tag:<28} {sanad}")
        else:
            broken += 1
            print(f"  {C_R}✗{C_0} {tag:<28} {why}")
    if corpus:
        corpus.close()
    print(f"\n  مُسنَد ومُفعَّل: {filled}   بلا سند: {empty}   معطوب: {broken}")
    print(f"{C_D}  البند بلا سند يُرصد ويُبلَّغ عنه، ولا يُفرض على العقد.{C_0}\n")
    return 1 if broken else 0


def cmd_propose(cfg: dict, db: str, out: Path, limit: int) -> int:
    try:
        corpus = Corpus(db)
    except FileNotFoundError as exc:
        print(f"{C_R}{exc}{C_0}", file=sys.stderr)
        print(f"{C_D}  ابنِ المدونة أولًا — الأسناد تُملأ منها لا من الذاكرة.{C_0}",
              file=sys.stderr)
        return 2

    items = [i for i in statutory_items(cfg) if not (i.get("sanad") or "").strip()]
    if not items:
        print(f"\n{C_G}✓ كل البنود القانونية مُسنَدة.{C_0}\n")
        corpus.close()
        return 0

    lines = [HEADER]
    total_candidates = 0
    for it in items:
        tag = f"{it['type']}/{it['key']}"
        lines.append(f"\n## {tag}\n")
        lines.append(f"**البند:** {it['label']}  ({it['type_name']}، "
                     f"{'إلزامي' if it['group'] == 'required' else 'يُرصد كباطل'})\n")
        lines.append(f"**القاعدة المطلوب إسنادها:** {it['why'].strip()}\n")

        seen: set[str] = set()
        hits = []
        for term in it.get("search_terms", []) or [it["label"]]:
            for h in corpus.search(term, practice_areas=[it["area"]] if it.get("area") else None,
                                   limit=limit):
                key = f"{h.instrument_id}:{h.article_key}"
                if key not in seen:
                    seen.add(key)
                    hits.append(h)
        hits = hits[:limit]
        total_candidates += len(hits)

        if not hits:
            lines.append("\n> لا مرشّحات في المدونة. قد يكون التشريع الحاكم غير "
                         "مستورد بعد.\n")
        for h in hits:
            lines.append(f"\n- `{h.marker}` — {h.label} من {h.instrument_title}\n"
                         f"  > {h.snippet(420)}\n")
        lines.append("\n**المعتمد:** \n\n---\n")

    corpus.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n══ اقتراح أسناد ══\n")
    print(f"  بنود بلا سند : {len(items)}")
    print(f"  مرشّحات       : {total_candidates}")
    print(f"\n  {C_G}✓{C_0} ورقة المراجعة: {out}")
    print(f"{C_D}  اقرأ نص كل مادة واعتمد ما يحمل القاعدة فعلًا. المشابهة في\n"
          f"  الألفاظ ليست إسنادًا، وترك الحقل فارغًا أسلم من سند خاطئ.\n\n"
          f"  ثم: python3 tools/contracts/fill_sanad.py --apply {out}{C_0}\n")
    return 0


_SECTION = re.compile(r"^##\s+(\S+?)/(\S+)\s*$", re.MULTILINE)


def parse_sheet(path: Path) -> dict[tuple[str, str], str]:
    """قراءة ما اعتُمد في ورقة المراجعة."""
    text = path.read_text(encoding="utf-8")
    out: dict[tuple[str, str], str] = {}
    marks = list(_SECTION.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end]
        am = re.search(r"\*\*المعتمد:\*\*(.*)", body)
        if not am:
            continue
        chosen = am.group(1).strip().strip("`").strip()
        if chosen:
            out[(m.group(1), m.group(2))] = chosen
    return out


def set_sanad(text: str, tkey: str, ikey: str, marker: str) -> tuple[str, bool]:
    """كتابة السند في موضعه نصيًا — حفاظًا على التعليقات والتنسيق.

    Rewriting the file through a YAML dumper would strip every comment in it,
    and those comments are what explain the structural/statutory distinction to
    whoever reads the file next.
    """
    # حدود قسم النوع
    tm = re.search(rf"^  {re.escape(tkey)}:$", text, re.MULTILINE)
    if not tm:
        return text, False
    nxt = re.search(r"^  \w[\w-]*:$", text[tm.end():], re.MULTILINE)
    t_end = tm.end() + (nxt.start() if nxt else len(text) - tm.end())
    block = text[tm.end():t_end]

    im = re.search(rf"^      - key: {re.escape(ikey)}$", block, re.MULTILINE)
    if not im:
        return text, False
    nxt_i = re.search(r"^      - key: ", block[im.end():], re.MULTILINE)
    i_end = im.end() + (nxt_i.start() if nxt_i else len(block) - im.end())
    item = block[im.end():i_end]

    new_item, n = re.subn(r'^        sanad: ".*"$',
                          f'        sanad: "{marker}"', item, count=1, flags=re.MULTILINE)
    if not n:
        return text, False
    new_block = block[:im.end()] + new_item + block[i_end:]
    return text[:tm.end()] + new_block + text[t_end:], True


def cmd_apply(sheet: Path, cfg: dict, db: str) -> int:
    if not sheet.exists():
        print(f"{C_R}ورقة المراجعة غير موجودة: {sheet}{C_0}", file=sys.stderr)
        return 2
    chosen = parse_sheet(sheet)
    if not chosen:
        print(f"\n{C_Y}لم يُعتمد أي سند في الورقة.{C_0}")
        print(f"{C_D}  اكتب علامة المادة في سطر «المعتمد» تحت كل بند.{C_0}\n")
        return 1

    try:
        corpus = Corpus(db)
    except FileNotFoundError as exc:
        print(f"{C_R}{exc}{C_0}", file=sys.stderr)
        return 2

    text = load_text()
    applied, rejected = [], []
    print(f"\n══ تطبيق الأسناد المعتمدة ══\n")
    for (tkey, ikey), marker in chosen.items():
        tag = f"{tkey}/{ikey}"
        cits = parse_all(marker)
        if not cits:
            rejected.append((tag, "علامة غير صالحة نحويًا"))
            continue
        ok, why = corpus.resolve(cits[0].instrument_id, cits[0].article_key)
        if not ok:
            rejected.append((tag, why))
            continue
        text, done = set_sanad(text, tkey, ikey, marker)
        (applied if done else rejected).append(
            (tag, marker) if done else (tag, "لم يُعثر على موضع البند في القوائم"))
    corpus.close()

    for tag, marker in applied:
        print(f"  {C_G}✓{C_0} {tag:<28} {marker}")
    for tag, why in rejected:
        print(f"  {C_R}✗{C_0} {tag:<28} {why}")

    if applied:
        CLAUSES.write_text(text, encoding="utf-8")
        print(f"\n  {C_G}✓ كُتب {len(applied)} سندًا في {CLAUSES.name}.{C_0}")
        print(f"{C_D}  هذه البنود صارت مفروضة على العقود بدل أن تُرصد فقط.{C_0}")
    if rejected:
        print(f"\n  {C_Y}{len(rejected)} سندًا لم يُطبَّق — لم يُحل إلى المدونة.{C_0}")
    print()
    return 1 if rejected else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="ملء أسناد بنود العقود من المدونة")
    ap.add_argument("--db", default=str(ROOT / "corpus/index/corpus.db"))
    ap.add_argument("--out", type=Path, default=DEFAULT_SHEET,
                    help="مسار ورقة المراجعة المقترحة")
    ap.add_argument("--apply", type=Path, metavar="SHEET",
                    help="تطبيق الأسناد المعتمدة في ورقة مراجعة")
    ap.add_argument("--status", action="store_true", help="عرض حالة الأسناد")
    ap.add_argument("--limit", type=int, default=4, help="عدد المرشّحات لكل بند")
    args = ap.parse_args()

    cfg = yaml.safe_load(CLAUSES.read_text(encoding="utf-8")) or {}
    if args.status:
        return cmd_status(cfg, args.db)
    if args.apply:
        return cmd_apply(args.apply, cfg, args.db)
    return cmd_propose(cfg, args.db, args.out, args.limit)


if __name__ == "__main__":
    sys.exit(main())
