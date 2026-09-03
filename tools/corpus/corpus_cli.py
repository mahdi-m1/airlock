#!/usr/bin/env python3
"""أداة البحث في المدونة القانونية — الأداة التي يستدعيها الوكلاء.

The corpus search tool agents call. Local read, zero network.

    corpus search "الفصل التعسفي" --area labour
    corpus article law:36/2012 111
    corpus stats

لماذا أداة سطر أوامر لا خادم MCP: خوادم MCP من نوع stdio تبقى في حالة draft
حتى يعتمدها المشغّل يدويًا، وهي لا تُشحن ضمن حزمة الشركة. سكربت في مساحة عمل
المشروع أبسط وأوثق وبلا احتكاك.

اقتصاد التوكنز: البحث يعيد مقاطع المواد المطابقة فقط — لا نصوص قوانين كاملة.
هذا هو الفرق بين دور بحث بمئات التوكنز وآخر بعشرات الآلاف.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from lib.citation import Citation  # noqa: E402
from lib.corpus import Corpus, gazette_ref  # noqa: E402

DEFAULT_DB = ROOT / "corpus/index/corpus.db"


def _open(db: str) -> Corpus:
    try:
        return Corpus(db)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)


def cmd_search(args) -> int:
    corpus = _open(args.db)
    hits = corpus.search(args.query, practice_areas=args.area or None,
                         instruments=args.instrument or None, limit=args.limit)
    if args.json:
        print(json.dumps([{
            "marker": h.marker, "instrument": h.instrument_title,
            "article": h.label, "text": h.snippet(args.chars),
            "gazette": h.gazette, "source_url": h.source_url,
        } for h in hits], ensure_ascii=False, indent=2))
        return 0 if hits else 1

    if not hits:
        print(f"لا نتائج في المدونة المحلية لـ: «{args.query}»\n"
              f"لا تستشهد بما لا تجده هنا — راجع أمين المصادر لتوسيع المدونة.")
        return 1

    print(f"\n{len(hits)} نتيجة — انسخ العلامة كما هي بعد كل إشارة قانونية:\n")
    for h in hits:
        print(f"── {h.label} من {h.instrument_title}")
        print(f"   العلامة: {h.marker}")
        print(f"   {h.snippet(args.chars)}")
        if h.gazette:
            print(f"   {h.gazette}")
        if h.source_url:
            print(f"   المصدر: {h.source_url}")
        print()
    return 0


def cmd_article(args) -> int:
    corpus = _open(args.db)
    inst = corpus.instrument(args.instrument)
    if inst is None:
        print(f"التشريع «{args.instrument}» غير موجود في المدونة المحلية.", file=sys.stderr)
        return 1
    art = corpus.article(args.instrument, args.article)
    if art is None:
        print(f"المادة ({args.article}) غير موجودة في «{inst['title']}».", file=sys.stderr)
        return 1
    marker = (f"⟦BH:{inst['type']}:{inst['number']}/{inst['year']}"
              f":م{art['number']}{'مكرر' if art['bis'] else ''}⟧")
    gz = gazette_ref(inst)
    if args.json:
        print(json.dumps({"marker": marker, "instrument": inst["title"],
                          "article": art["label"], "text": art["text"],
                          "gazette": gz, "source_url": inst["source_url"],
                          "citable": bool(inst["verified"])},
                         ensure_ascii=False, indent=2))
        return 0
    print(f"\n{art['label']} من {inst['title']}")
    print(f"العلامة: {marker}\n\n{art['text']}\n")
    if gz:
        print(gz)
    if inst["source_url"]:
        print(f"المصدر: {inst['source_url']}")
    if not inst["verified"]:
        print("\n⚠ غير قابل للاستشهاد — التوثيق ناقص.")
    print()
    return 0


def cmd_verify(args) -> int:
    """تحقق سريع من قابلية حل استشهاد — يستعمله الوكلاء قبل التسليم."""
    corpus = _open(args.db)
    from lib.citation import parse_all
    cits = parse_all(args.marker)
    if not cits:
        print(f"علامة غير صالحة نحويًا: {args.marker}", file=sys.stderr)
        return 2
    c: Citation = cits[0]
    ok, why = corpus.resolve(c.instrument_id, c.article_key)
    print("✓ يُحل" if ok else f"✗ {why}")
    return 0 if ok else 1


def cmd_stats(args) -> int:
    corpus = _open(args.db)
    st = corpus.stats()
    print(f"\nالمدونة القانونية المحلية")
    print(f"  التشريعات   : {st['verified']} مُتحقق من {st['instruments']}")
    print(f"  المواد      : {st['articles']}")
    if st["oldest_retrieved_at"]:
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(st["oldest_retrieved_at"])).days
            print(f"  أقدم استيراد: قبل {age} يوم")
        except ValueError:
            pass
    print()
    if st["verified"] == 0:
        print("⚠ لا تشريع مُتحقق — المكتب لا يستطيع إصدار أي إسناد.\n")
        return 1
    for row in corpus.db.execute(
            "SELECT i.id,i.title,i.verified,COUNT(a.article_key) n FROM instruments i "
            "LEFT JOIN articles a ON a.instrument_id=i.id GROUP BY i.id ORDER BY i.id"):
        print(f"  {'✓' if row['verified'] else '~'} {row['id']:<16} "
              f"{row['n']:>4} مادة   {row['title']}")
    print()
    _next_step(corpus, st)
    return 0


def _next_step(corpus: Corpus, st: dict) -> None:
    """الخطوة التالية في بناء المدونة — بناءً على حالتها الفعلية.

    بناء المدونة عدة مراحل يسهل نسيان ترتيبها، وكل مرحلة تُغيّر ما يفعله
    المكتب: بلا مدونة لا إسناد، وبلا معايرة عتبة مُخمَّنة، وبلا أسناد يبقى
    فاحص العقود منبّهًا لا حاجزًا. فالأداة تقول أين أنت وما التالي.
    """
    import json as _json

    sources = ROOT / "corpus/sources.yaml"
    want: list[str] = []
    if sources.exists():
        import yaml
        cfg = yaml.safe_load(sources.read_text(encoding="utf-8")) or {}
        have = {r["key"] for r in corpus.db.execute("SELECT key FROM instruments")}
        want = [i["key"] for i in cfg.get("instruments", []) if i["key"] not in have]

    print("الخطوة التالية:")
    if want:
        print(f"  ينقص {len(want)} تشريعًا. نزّل نصوصها الرسمية إلى corpus/staging/")
        for k in want[:4]:
            print(f"    corpus/staging/{k}.html")
        if len(want) > 4:
            print(f"    … و{len(want) - 4} غيرها")
        print("  ثم:  python3 tools/ingest/ingest.py --from-staging")
        print()
        return

    calib = ROOT / "corpus/index/calibration.json"
    reliable = False
    if calib.exists():
        try:
            reliable = bool(_json.loads(calib.read_text(encoding="utf-8")).get("reliable"))
        except ValueError:
            pass
    if not reliable:
        print("  المدونة مكتملة. عايِر عتبة التدقيق الدلالي:")
        print("    python3 scripts/calibrate-threshold.py --write")
        print()
        return

    clauses = ROOT / "config/clauses.yaml"
    if clauses.exists() and 'sanad: ""' in clauses.read_text(encoding="utf-8"):
        print("  العتبة مُعايَرة. املأ أسناد بنود العقود لتُفرض بدل أن تُرصد:")
        print("    python3 tools/contracts/fill_sanad.py")
        print()
        return

    print("  المدونة جاهزة والعتبة مُعايَرة والأسناد مملوءة.")
    print("  راجع دوريًا:  python3 tools/contracts/fill_sanad.py --status")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(prog="corpus", description="المدونة القانونية البحرينية المحلية")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="بحث عن مواد بموضوع")
    s.add_argument("query")
    s.add_argument("--area", action="append", choices=["civil", "commercial", "labour"])
    s.add_argument("--instrument", action="append", metavar="law:36/2012")
    s.add_argument("--limit", type=int, default=6)
    s.add_argument("--chars", type=int, default=700, help="أقصى طول للمقطع")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_search)

    a = sub.add_parser("article", help="عرض مادة بعينها")
    a.add_argument("instrument", metavar="law:36/2012")
    a.add_argument("article", metavar="111")
    a.add_argument("--json", action="store_true")
    a.set_defaults(fn=cmd_article)

    v = sub.add_parser("verify", help="تحقق من قابلية حل علامة استشهاد")
    v.add_argument("marker")
    v.set_defaults(fn=cmd_verify)

    st = sub.add_parser("stats", help="حالة المدونة")
    st.set_defaults(fn=cmd_stats)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
