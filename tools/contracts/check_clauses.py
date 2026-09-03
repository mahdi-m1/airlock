#!/usr/bin/env python3
"""فاحص بنود العقود — الحاجز بين المكتب وعقد ناقص أو باطل.

The contract clause checker. Contracts fail differently from memoranda: not by
a fabricated citation but by a **missing** clause or a **void** one.

  * الناقص لا يُرى وقت التوقيع، ويظهر عند النزاع حين لا يجد الطرف ما يحتج به.
  * الباطل أسوأ: يطمئن العميل إلى حماية لا وجود لها. شرط يُسقط حقًا آمرًا لا
    يصير صحيحًا لأن الطرف الآخر وقّع عليه.

القوائم في `config/clauses.yaml`، ولكل بند `basis` يحدد كيف يُعامَل:

  structural — انضباط صياغة لا حكم قانوني (تحديد الأطراف، الاختصاص،
               الإخطارات). يُفرض مباشرة.
  statutory  — مبني على نص بحريني. **لا يُفرض إلا بسند يُحل إلى المدونة.**
               بلا سند يُبلَّغ كتحقق يدوي، فلا يفرض المكتب على عقود عملائه
               قاعدة لم يتثبّت أحد من مصدرها.

    check_clauses.py عقد.md --type amal
    check_clauses.py --list
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

from lib.arabic import fold  # noqa: E402
from lib.citation import parse_all  # noqa: E402

C_R, C_G, C_Y, C_D, C_0 = "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"
# ‏<…> حقل يُملأ، و[اختر: …] بديل يُحسم. كلاهما لا يجوز بقاؤه في عقد يُوقَّع.
PLACEHOLDER = re.compile(r"<[^<>\n]{1,80}>|\[اختر:[^\]\n]{1,160}\]")


def load_config() -> dict:
    p = ROOT / "config/clauses.yaml"
    if not p.exists():
        raise SystemExit(f"{C_R}قوائم البنود غير موجودة: {p}{C_0}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def present(text_folded: str, patterns: list[str]) -> bool:
    return any(fold(p) in text_folded for p in patterns)


def sanad_resolves(sanad: str, db: str) -> tuple[bool, str]:
    """هل يُحل سند البند إلى المدونة المحلية؟"""
    if not (sanad or "").strip():
        return False, "بلا سند"
    cits = parse_all(sanad)
    if not cits:
        return False, "علامة سند غير صالحة نحويًا"
    try:
        from lib.corpus import Corpus
        corpus = Corpus(db)
    except FileNotFoundError:
        return False, "المدونة غير مبنية"
    ok, why = corpus.resolve(cits[0].instrument_id, cits[0].article_key)
    corpus.close()
    return ok, "" if ok else why


def check(path: Path, ctype: str, cfg: dict, db: str) -> dict:
    text = path.read_text(encoding="utf-8")
    folded = fold(text)
    types = cfg.get("types", {})
    if ctype not in types:
        raise SystemExit(f"{C_R}نوع عقد غير معروف: «{ctype}». "
                         f"المتاح: {'، '.join(types)}{C_0}")
    spec = types[ctype]

    required = list(cfg.get("common", {}).get("required", [])) + \
        list(spec.get("required", []))
    problems: list[dict] = []
    manual: list[dict] = []
    found: list[str] = []

    # ── البنود الإلزامية ──
    for item in required:
        if present(folded, item["patterns"]):
            found.append(item["label"])
            continue
        if item.get("basis") == "statutory":
            ok, why = sanad_resolves(item.get("sanad", ""), db)
            if not ok:
                manual.append({"label": item["label"], "why": item["why"],
                               "reason": why, "kind": "ناقص"})
                continue
        problems.append({"label": item["label"], "why": item["why"], "kind": "ناقص"})

    # ── البنود الباطلة ──
    for item in spec.get("void", []):
        if not present(folded, item["patterns"]):
            continue
        if item.get("basis") == "statutory":
            ok, why = sanad_resolves(item.get("sanad", ""), db)
            if not ok:
                manual.append({"label": item["label"], "why": item["why"],
                               "reason": why, "kind": "باطل"})
                continue
        problems.append({"label": item["label"], "why": item["why"], "kind": "باطل"})

    # ── حقول لم تُملأ ──
    holes = sorted(set(PLACEHOLDER.findall(text)))

    return {
        "file": str(path), "type": ctype, "type_name": spec.get("name", ctype),
        "passed": not problems and not holes,
        "found": found, "problems": problems, "manual": manual,
        "placeholders": holes,
    }


def cmd_list(cfg: dict) -> int:
    print("\n══ أنواع العقود وقوالبها ══\n")
    for key, spec in cfg.get("types", {}).items():
        n_req = len(cfg.get("common", {}).get("required", [])) + len(spec.get("required", []))
        n_void = len(spec.get("void", []))
        print(f"  {C_G}{key:<10}{C_0} {spec.get('name','')}")
        print(f"    {C_D}{n_req} بندًا إلزاميًا · {n_void} بندًا يُرصد كباطل{C_0}")
        print(f"    {C_D}{spec.get('template','')}{C_0}\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="فحص بنود العقود")
    ap.add_argument("file", nargs="?", type=Path)
    ap.add_argument("--type", help="نوع العقد (amal, ijar, bay, khadamat, ifsha, taswiya)")
    ap.add_argument("--db", default=str(ROOT / "corpus/index/corpus.db"))
    ap.add_argument("--list", action="store_true", help="عرض الأنواع والقوالب")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    if args.list:
        return cmd_list(cfg)
    if not args.file or not args.type:
        ap.error("مطلوب مسار العقد و--type، أو --list")
    if not args.file.exists():
        print(f"{C_R}الملف غير موجود: {args.file}{C_0}", file=sys.stderr)
        return 2

    rep = check(args.file, args.type, cfg, args.db)

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"\n══ فحص بنود — {args.file.name} ══")
        print(f"{C_D}النوع: {rep['type_name']}   البنود المستوفاة: "
              f"{len(rep['found'])}{C_0}\n")
        for p in rep["problems"]:
            mark = "بند إلزامي ناقص" if p["kind"] == "ناقص" else "بند باطل"
            print(f"  {C_R}✗{C_0} {mark}: {p['label']}")
            print(f"    {C_D}{p['why']}{C_0}")
        if rep["placeholders"]:
            print(f"  {C_R}✗{C_0} {len(rep['placeholders'])} حقلًا لم يُملأ:")
            for h in rep["placeholders"][:8]:
                print(f"    {C_D}{h}{C_0}")
            if len(rep["placeholders"]) > 8:
                print(f"    {C_D}… و{len(rep['placeholders']) - 8} غيرها{C_0}")
        for m in rep["manual"]:
            print(f"  {C_Y}?{C_0} تحقق يدوي — {m['label']} ({m['reason']})")
            print(f"    {C_D}{m['why']}{C_0}")
        print()
        if rep["passed"] and not rep["manual"]:
            print(f"{C_G}✓ العقد مكتمل البنود.{C_0}\n")
        elif rep["passed"]:
            print(f"{C_Y}⚠ البنود البنيوية مستوفاة، و{len(rep['manual'])} بندًا "
                  f"قانونيًا يحتاج تحققًا يدويًا.{C_0}")
            print(f"{C_D}  هذه بنود مبنية على نصوص بحرينية لم تُسنَد بعد في\n"
                  f"  config/clauses.yaml، فالفاحص يُبلّغ عنها ولا يفرضها.{C_0}\n")
        else:
            n = len(rep["problems"]) + (1 if rep["placeholders"] else 0)
            print(f"{C_R}✗ العقد غير صالح للتسليم — {n} مشكلة.{C_0}")
            print(f"{C_D}  حقل غير مملوء في عقد موقّع فراغ يملؤه الخصم،\n"
                  f"  وبند باطل يطمئن العميل إلى حماية لا وجود لها.{C_0}\n")

    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
