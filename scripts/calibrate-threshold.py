#!/usr/bin/env python3
"""معايرة عتبة التداخل الدلالي على المدونة الحقيقية.

Calibrates the semantic overlap threshold against the corpus that actually
exists on this machine, and writes the result where the citation gate reads it.

يُشغَّل بعد كل توسيع للمدونة. العتبة المكتوبة في `config/office.yaml` بقيمة
`auto` تُقرأ من هنا، فترتفع من تلقاء نفسها كلما كبرت المدونة — دون أن يعتمد
ذلك على تذكّر أحد.

    python3 scripts/calibrate-threshold.py            # عرض التوصية
    python3 scripts/calibrate-threshold.py --write    # اعتمادها
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import yaml  # noqa: E402

from lib import calibrate as cal  # noqa: E402
from lib.corpus import Corpus  # noqa: E402

C_R, C_G, C_Y, C_D, C_0 = "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"
OUT = ROOT / "corpus/index/calibration.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="معايرة عتبة التداخل الدلالي")
    ap.add_argument("--db", default=str(ROOT / "corpus/index/corpus.db"))
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--write", action="store_true",
                    help="كتابة العتبة المُعايَرة لتعتمدها البوابة")
    ap.add_argument("--force", action="store_true",
                    help="الكتابة رغم أن المعايرة غير موثوقة (غير مستحسن)")
    ap.add_argument("--miss-rate", type=float, default=0.05,
                    help="أقصى نسبة إسناد مغلوط يُقبل مرورها دون تحكيم (افتراضي 5%%)")
    args = ap.parse_args()

    try:
        corpus = Corpus(args.db)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    rows = [(r["instrument_id"], r["text"]) for r in corpus.db.execute(
        "SELECT a.instrument_id, a.text FROM articles a "
        "JOIN instruments i ON i.id = a.instrument_id WHERE i.verified = 1")]
    idf = corpus.term_idf()
    corpus.close()

    print(f"\n══ معايرة عتبة التداخل الدلالي ══")
    print(f"{C_D}المدونة: {len(rows)} مادة مُتحقق منها{C_0}\n")

    if not rows:
        print(f"{C_R}لا مواد مُتحقق منها — ابنِ المدونة أولًا:{C_0}")
        print(f"{C_D}  python3 tools/ingest/ingest.py --from-staging{C_0}\n")
        return 1

    print(f"{C_D}يبني أزواجًا موجبة (ادعاء من المادة نفسها) وسالبة (نفس الادعاء\n"
          f"منسوبًا لمادة أخرى، مرجّحة للمجاورة في نفس التشريع)…{C_0}")
    res = cal.calibrate(rows, idf, target_miss_rate=args.miss_rate)

    cur = yaml.safe_load((ROOT / "config/office.yaml").read_text(encoding="utf-8"))
    configured = (cur or {}).get("citations", {}).get("min_semantic_overlap")

    print(f"\n  العتبة الموصى بها : {C_G}{res.threshold}{C_0}")
    print(f"  العتبة الحالية    : {configured}")
    print(f"  عيّنات القياس     : {res.samples}")
    if res.samples and res.miss_rate is not None:
        print(f"\n  {C_D}عند هذه العتبة:{C_0}")
        print(f"    إسناد مغلوط يمر دون تحكيم : {res.miss_rate:.0%}")
        print(f"    إسناد سليم يُحال للتحكيم   : {res.adjudication_rate:.0%}")

    icon, col = ("✓", C_G) if res.reliable else ("!", C_Y)
    print(f"\n  {col}{icon}{C_0} {res.note}")

    if args.write and not res.reliable and not args.force:
        print(f"\n  {C_R}✗ لم تُكتب.{C_0} معايرة على مدونة بهذا الحجم قد تُنتج عتبة "
              f"{C_R}أدنى{C_0} من الافتراضية،\n    فتُضعف الفحص بدل أن تقوّيه — "
              f"وهو عكس الغرض منها.")
        print(f"    {C_D}وسّع المدونة إلى {cal.MIN_ARTICLES}+ مادة ثم أعد المعايرة، "
              f"أو مرّر --force إن كنت متيقنًا.{C_0}\n")
        return 1

    if args.write:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(res.to_json(), encoding="utf-8")
        print(f"\n  {C_G}✓{C_0} كُتبت العتبة: {args.out}")
        if configured == "auto" and res.threshold < 0.35:
            print(f"  {C_Y}!{C_0} العتبة الجديدة أدنى من الافتراضية (0.35): "
                  f"سيقل التحكيم ويرتفع احتمال الفوات.")
        if configured != "auto":
            print(f"  {C_Y}!{C_0} لن تُعتمد ما دام min_semantic_overlap في "
                  f"config/office.yaml قيمته «{configured}».")
            print(f"    {C_D}اجعلها «auto» لتقرأ البوابة العتبة المُعايَرة.{C_0}")
    else:
        print(f"\n  {C_D}للاعتماد:  python3 scripts/calibrate-threshold.py --write{C_0}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
