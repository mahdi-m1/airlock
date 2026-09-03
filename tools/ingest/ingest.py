#!/usr/bin/env python3
"""استيراد المدونة القانونية من المصادر الرسمية البحرينية.

Builds the local legal corpus. Runs ONLY in the archivist's network lane, whose
allowlist is derived from `corpus/sources.yaml → domains`. It never sees case
data — by construction it runs in a separate project from every case agent.

وضعان:
  --from-staging   تحليل ملفات رسمية مُنزَّلة مسبقًا (الأوثق — موصى به)
  --fetch          تنزيل آلي من روابط مُعرَّفة في sources.yaml

كل تشريع يُتحقق من عنوانه بمقارنة النص المُستورد بالعنوان المُعلن، ولا يُوسَم
verified إلا بعد المطابقة. الوكلاء لا يستطيعون الاستشهاد بغير المُتحقق منه.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import yaml  # noqa: E402

from lib import arabic, extract  # noqa: E402
from lib.corpus import Corpus  # noqa: E402

C_R, C_G, C_Y, C_D, C_0 = "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"


def load_sources(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def instrument_id(inst: dict) -> str:
    return f"{inst['type']}:{inst['number']}/{inst['year']}"


def find_staged(staging: Path, key: str) -> Path | None:
    """أول ملف مُجهَّز يطابق مفتاح التشريع."""
    for suffix in extract.SUPPORTED_SUFFIXES + (".pdf",):
        p = staging / f"{key}{suffix}"
        if p.exists():
            return p
    hits = sorted(staging.glob(f"{key}.*"))
    return hits[0] if hits else None


def fetch(url: str, ua: str, timeout: int, allowed: set[str]) -> tuple[str, str]:
    """تنزيل مصدر رسمي. يرفض أي نطاق خارج قائمة السماح — دفاع في العمق."""
    host = (urlparse(url).hostname or "").lower()
    if host not in allowed:
        raise PermissionError(
            f"النطاق «{host}» خارج قائمة السماح في sources.yaml — رُفض التنزيل")
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": ua, "Accept-Language": "ar,en;q=0.7"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        raw = resp.read()
    for enc in ("utf-8", "windows-1256"):
        try:
            return raw.decode(enc), url
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), url


def main() -> int:
    ap = argparse.ArgumentParser(
        description="استيراد المدونة القانونية البحرينية إلى مخزن محلي",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("--sources", default=str(ROOT / "corpus/sources.yaml"))
    ap.add_argument("--from-staging", action="store_true",
                    help="تحليل الملفات المُنزَّلة في مجلد التجهيز (الوضع الافتراضي)")
    ap.add_argument("--fetch", action="store_true",
                    help="تنزيل آلي من الروابط المُعرَّفة (يتطلب مسار المصادر الشبكي)")
    ap.add_argument("--only", nargs="*", metavar="KEY",
                    help="اقتصار الاستيراد على مفاتيح تشريعات محددة")
    ap.add_argument("--force-unverified", action="store_true",
                    help="استيراد رغم فشل مطابقة العنوان (يبقى verified=false)")
    args = ap.parse_args()

    src = load_sources(Path(args.sources))
    cfg = src.get("ingest", {})
    staging = ROOT / cfg.get("staging_dir", "corpus/staging")
    db_path = ROOT / cfg.get("index_db", "corpus/index/corpus.db")
    threshold = float(cfg.get("title_match_threshold", 0.6))
    allowed = {d["host"].lower() for d in src.get("domains", [])}
    staging.mkdir(parents=True, exist_ok=True)

    instruments = src.get("instruments", [])
    if args.only:
        instruments = [i for i in instruments if i["key"] in set(args.only)]
        if not instruments:
            print(f"{C_R}لا تشريع يطابق: {' '.join(args.only)}{C_0}")
            return 1

    corpus = Corpus(db_path, write=True)
    ok = skipped = failed = 0

    print(f"\n══ استيراد المدونة القانونية ══")
    print(f"{C_D}المصادر: {args.sources}{C_0}")
    print(f"{C_D}المخزن : {db_path}{C_0}\n")

    for inst in instruments:
        key, iid = inst["key"], instrument_id(inst)
        label = f"{inst['title']} ({inst['number']}/{inst['year']})"

        # ── الحصول على النص ──
        text = title_hint = source_url = None
        try:
            if args.fetch and inst.get("url"):
                html, source_url = fetch(
                    inst["url"], cfg.get("user_agent", "airlock/1.0"),
                    int(cfg.get("request_timeout_sec", 30)), allowed)
                text, title_hint = extract.from_html(html)
            else:
                staged = find_staged(staging, key)
                if staged is None:
                    print(f"  {C_Y}⊘{C_0} {label}\n"
                          f"      {C_D}لا ملف مُجهَّز. نزّل النص الرسمي إلى: "
                          f"{staging}/{key}.html{C_0}")
                    skipped += 1
                    continue
                if (reason := extract.unsupported_reason(staged)):
                    print(f"  {C_Y}⊘{C_0} {label}\n      {C_D}{reason}{C_0}")
                    skipped += 1
                    continue
                text, title_hint = extract.from_file(staged)
                source_url = inst.get("url")
        except Exception as exc:
            print(f"  {C_R}✗{C_0} {label}\n      {C_D}{type(exc).__name__}: {exc}{C_0}")
            failed += 1
            continue

        if not text or len(text) < 200:
            print(f"  {C_R}✗{C_0} {label}\n      {C_D}النص المُستخرج فارغ أو قصير جدًا{C_0}")
            failed += 1
            continue

        # ── التحقق من العنوان ──
        haystack = f"{title_hint}\n{text[:4000]}"
        match = max(arabic.similarity(inst["title"], line)
                    for line in haystack.split("\n") if line.strip()) if haystack.strip() else 0.0
        # العنوان قد يرد كجزء من سطر أطول ("بإصدار قانون العمل في القطاع الأهلي")
        if arabic.fold(inst["title"]) in arabic.fold(haystack):
            match = 1.0
        verified = match >= threshold

        # ── التقسيم ──
        articles = arabic.segment_articles(text)
        if not articles:
            print(f"  {C_R}✗{C_0} {label}\n      {C_D}لم يُعثر على أي مادة — تحقق من تنسيق الملف{C_0}")
            failed += 1
            continue
        if not verified and not args.force_unverified:
            print(f"  {C_R}✗{C_0} {label}\n"
                  f"      {C_D}تعارض عنوان: التطابق {match:.0%} < {threshold:.0%}. "
                  f"العنوان في المصدر قد يختلف عن المُعلن في sources.yaml.{C_0}\n"
                  f"      {C_D}راجع الملف، أو مرّر --force-unverified للاستيراد بلا توثيق.{C_0}")
            failed += 1
            continue

        corpus.put_instrument(
            id=iid, key=key, type=inst["type"], number=str(inst["number"]),
            year=str(inst["year"]), title=inst["title"], source_url=source_url,
            source_domain=(urlparse(source_url).hostname if source_url else None),
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            verified=verified, title_match=round(match, 3),
            practice_areas=inst.get("practice_areas", []))
        n = corpus.put_articles(iid, articles)
        corpus.commit()

        mark = f"{C_G}✓{C_0}" if verified else f"{C_Y}~{C_0}"
        note = "" if verified else f" {C_Y}(غير مُتحقق){C_0}"
        print(f"  {mark} {label} — {n} مادة{note}")
        ok += 1

    # ── التصدير والخلاصة ──
    if ok:
        jsonl = ROOT / cfg.get("records_jsonl", "corpus/index/records.jsonl")
        corpus.export_jsonl(jsonl)
    st = corpus.stats()
    corpus.close()

    print(f"\n{C_D}{'─' * 58}{C_0}")
    print(f"  مستورد: {ok}   متخطّى: {skipped}   فاشل: {failed}")
    print(f"  المدونة: {st['verified']}/{st['instruments']} تشريع مُتحقق، "
          f"{st['articles']} مادة")
    if skipped:
        print(f"\n{C_D}  الملفات المتخطاة تحتاج تنزيلًا يدويًا من المصادر الرسمية إلى:\n"
              f"    {staging}{C_0}")
    if st["verified"] == 0:
        print(f"\n{C_R}  ⚠ لا يوجد أي تشريع مُتحقق — المكتب لا يستطيع إصدار أي إسناد.{C_0}")
        return 1
    print()
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
