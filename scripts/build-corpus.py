#!/usr/bin/env python3
"""بناء المدونة القانونية من المصادر الرسمية — الدورة كاملة بأمر واحد.

    python3 scripts/build-corpus.py             # الدورة كاملة
    python3 scripts/build-corpus.py --plan      # ماذا سيفعل، دون أن يفعل
    python3 scripts/build-corpus.py --only civil-code labour-private-sector
    python3 scripts/build-corpus.py --no-fetch  # من الملفات المُجهَّزة فقط
    python3 scripts/build-corpus.py --refresh   # أعد التنزيل ولو كان مُجهَّزًا

يُشغَّل في مسار وكيل المصادر (archivist) وحده — المسار الشبكي الذي لا يرى أي
بيانات قضايا. لا يُشغَّل من مسار القضايا إطلاقًا.

الترتيب:
  ١· فحص سجل المصادر: ما الجاهز للتنزيل، وما المُجهَّز، وما ينقصه توثيق.
  ٢· تنزيل من الروابط المسجّلة — داخل قائمة السماح، وكل تحويلة تُفحص على حدة.
  ٣· تحويل PDF/Word/صور إلى نص بالمستخرج المُحصَّن، مع إعلان ثقة الاستخراج.
  ٤· استيراد: تقسيم مواد، مطابقة عنوان، بوابة توثيق (tools/ingest).
  ٥· معايرة عتبة التدقيق الدلالي متى كبرت المدونة كفاية.
  ٦· تقرير بما بقي — أمر جاهز للنسخ لكل تشريع ناقص.

وما لا يفعله، عمدًا: لا يخترع رابطًا ولا رقم جريدة ولا سطرًا من نص قانوني.
التشريع بلا مصدر رسمي مسجَّل يبقى ناقصًا ويُعلَن نقصه — لأن تشريعًا مفقودًا
تعرفه أأمن من تشريع ملفَّق لا تعرفه.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import yaml  # noqa: E402

from lib import discover, documents, extract  # noqa: E402

# تسجيل الرابط يعيش في المستورد ومعه فحص النطاق وحفظ تعليقات السجل — يُستورد
# بدل أن يُكرَّر، فنسختان من قاعدة أمنية واحدة تفترقان عاجلًا.
_spec = importlib.util.spec_from_file_location("ingest_mod", ROOT / "tools/ingest/ingest.py")
_ingest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ingest)
set_url = _ingest.set_url

C_R, C_G, C_Y, C_B, C_D, C_0 = (
    "\033[31m", "\033[32m", "\033[33m", "\033[1m", "\033[2m", "\033[0m")

MAX_DOWNLOAD_BYTES = documents.MAX_FILE_BYTES
FMT_SUFFIX = {"pdf": ".pdf", "docx": ".docx", "odt": ".odt", "rtf": ".rtf",
              "html": ".html", "text": ".txt", "png": ".png", "jpeg": ".jpg",
              "tiff": ".tiff", "gif": ".gif", "bmp": ".bmp", "webp": ".webp"}


# ── التنزيل ───────────────────────────────────────────────────────────
class _AllowlistRedirect(urllib.request.HTTPRedirectHandler):
    """يفحص كل تحويلة على حدة.

    التحقق من النطاق مرة واحدة قبل الطلب لا يكفي: صفحة رسمية قد تحوّل إلى
    مضيف آخر — وسيط تحميل أو مختصر روابط — فيدخل المدونة نصٌّ لا نعرف مصدره
    بينما السجل يقول إنه من نطاق رسمي.
    """

    def __init__(self, allowed: set[str], hops: list[str]):
        self.allowed, self.hops = allowed, hops

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = (urlparse(newurl).hostname or "").lower()
        if host not in self.allowed:
            raise PermissionError(
                f"تحويلة إلى نطاق خارج قائمة السماح: «{host}» ({newurl})")
        self.hops.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def get(url: str, ua: str, timeout: int, allowed: set[str]) -> dict:
    """طلب واحد لمصدر رسمي، بقائمة السماح مفروضة على كل تحويلة."""
    host = (urlparse(url).hostname or "").lower()
    if host not in allowed:
        raise PermissionError(f"النطاق «{host}» خارج قائمة السماح في sources.yaml")

    hops: list[str] = []
    opener = urllib.request.build_opener(_AllowlistRedirect(allowed, hops))
    req = urllib.request.Request(url, headers={
        "User-Agent": ua, "Accept-Language": "ar,en;q=0.7"})
    with opener.open(req, timeout=timeout) as resp:  # noqa: S310
        raw = resp.read(MAX_DOWNLOAD_BYTES + 1)
        status, ctype, final = resp.status, resp.headers.get("Content-Type", ""), resp.url
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"حجم الملف يتجاوز {MAX_DOWNLOAD_BYTES // 1048576} ميغابايت")
    if not raw:
        raise ValueError("الاستجابة فارغة")
    return {"raw": raw, "status": status, "content_type": ctype,
            "final_url": final, "hops": hops}


def download(url: str, key: str, staging: Path, ua: str, timeout: int,
             allowed: set[str]) -> dict:
    """تنزيل مصدر رسمي إلى مجلد التجهيز. يعيد سجل التنزيل للسجلّ المرافق."""
    r = get(url, ua, timeout, allowed)
    raw, status, ctype = r["raw"], r["status"], r["content_type"]
    final, hops = r["final_url"], r["hops"]

    # الامتداد من بايتات الملف لا من ترويسة الخادم: الترويسة قد تكذب،
    # والصيغة الحقيقية هي ما يقرؤه المستخرج بعد قليل.
    tmp = staging / f".{key}.part"
    tmp.write_bytes(raw)
    fmt = documents.detect_format(tmp)
    suffix = FMT_SUFFIX.get(fmt)
    if suffix is None:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"صيغة غير مدعومة من الخادم ({fmt}، Content-Type: {ctype})")
    dest = staging / f"{key}{suffix}"
    tmp.replace(dest)

    import hashlib
    return {"key": key, "url": url, "final_url": final, "hops": hops,
            "status": status, "content_type": ctype, "format": fmt,
            "bytes": len(raw), "file": dest.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


# ── التحويل إلى نص ────────────────────────────────────────────────────
def to_text(path: Path, *, accept_low: bool) -> tuple[Path | None, str]:
    """تحويل ملف غير نصي إلى نص يبتلعه المستورد. يعيد (المسار، ملاحظة)."""
    if extract.unsupported_reason(path) is None:
        return path, ""
    txt = path.with_suffix(".txt")
    if txt.exists() and txt.stat().st_mtime >= path.stat().st_mtime:
        return txt, "نصٌّ محوَّل موجود"
    try:
        ex = documents.extract(path, expect_arabic=True)
    except Exception as exc:  # noqa: BLE001 — الرسالة تُعرض للمستخدم كما هي
        return None, f"{type(exc).__name__}: {exc}"
    note = f"{ex.method}، ثقة {ex.confidence:.0%}"
    if ex.pages:
        note += f"، {ex.pages} صفحة"
    if not ex.ok and not accept_low:
        detail = "؛ ".join(ex.warnings[:2]) or "ثقة منخفضة"
        return None, (f"{note} — رُفض: {detail}\n"
                      f"      استخراج عربي مشوّه يدخل المدونة نصًّا يبدو سليمًا "
                      f"وليس كذلك.\n"
                      f"      حوّله بنفسك ثم ضعه في {txt.name}، أو مرّر "
                      f"--accept-low-confidence.")
    txt.write_text(ex.text, encoding="utf-8")
    if ex.warnings:
        note += " ⚠ " + "؛ ".join(ex.warnings[:2])
    return txt, note


# ── الفحص ─────────────────────────────────────────────────────────────
def provenance_gap(inst: dict) -> list[str]:
    gap = []
    if not (inst.get("url") or "").strip():
        gap.append("رابط")
    if not str(inst.get("gazette_issue") or "").strip():
        gap.append("عدد الجريدة")
    if not str(inst.get("gazette_date") or "").strip():
        gap.append("تاريخ النشر")
    return gap


def staged_file(staging: Path, key: str) -> Path | None:
    for suffix in extract.SUPPORTED_SUFFIXES + tuple(FMT_SUFFIX.values()):
        p = staging / f"{key}{suffix}"
        if p.exists():
            return p
    return None


def survey(instruments: list[dict], staging: Path, *, refresh: bool,
           fetch: bool) -> list[dict]:
    plan = []
    for inst in instruments:
        have = staged_file(staging, inst["key"])
        url = (inst.get("url") or "").strip()
        if url and fetch and (refresh or have is None):
            action = "fetch"
        elif have is not None:
            action = "staged"
        else:
            action = "manual"
        plan.append({"inst": inst, "action": action, "file": have, "url": url,
                     "gap": provenance_gap(inst)})
    return plan


# ── الاستكشاف من فهرس رسمي ────────────────────────────────────────────
def cmd_discover(src: dict, catalogs: list[str], instruments: list[dict],
                 ua: str, timeout: int, allowed: set[str], sources_path: str,
                 *, write: bool) -> int:
    """مطابقة روابط فهرس رسمي بالتشريعات التي لا رابط لها.

    الفهرس يوفّر أشق خطوة في بناء المدونة — العثور على صفحة كل تشريع — لكنه
    لا يوفّر التحقق: نص الرابط قد يكون عنوانًا مختصرًا أو عنوان مرسوم تعديل.
    فالأداة ترشّح وتشرح سبب الترشيح، والقرار يبقى للمشغّل.
    """
    pending = [i for i in instruments if not (i.get("url") or "").strip()]
    if not pending:
        print(f"  {C_G}كل تشريع في السجل له رابط مسجَّل — لا شيء لاستكشافه.{C_0}\n")
        return 0
    if not catalogs:
        print(f"  {C_Y}لا فهرس مسجَّلًا.{C_0} أضِف صفحات الفهارس تحت `catalogs` في "
              f"sources.yaml،\n  أو مرّرها: --discover \"https://…\"\n")
        return 1

    found: list[discover.Link] = []
    for url in catalogs:
        try:
            r = get(url, ua, timeout, allowed)
        except Exception as exc:  # noqa: BLE001
            print(f"  {C_R}✗{C_0} {url}\n      {C_D}{type(exc).__name__}: {exc}{C_0}")
            continue
        html = documents.decode_text(r["raw"])[0] or r["raw"].decode("utf-8", "replace")
        page = discover.links(html, r["final_url"])
        found.extend(page)
        print(f"  {C_G}✓{C_0} {url}  {C_D}{len(page)} رابطًا{C_0}")
    if not found:
        print(f"\n  {C_Y}لم يُقرأ أي رابط من الفهارس.{C_0}\n")
        return 1

    hits = discover.match(pending, found)
    print(f"\n  {len(found)} رابطًا مقروءًا · مرشّحات لـ{len(hits)} من "
          f"{len(pending)} تشريعًا ناقصًا\n")

    recorded = 0
    for inst in pending:
        cands = hits.get(inst["key"])
        print(f"  ── {inst['title']} ({inst['number']}/{inst['year']})")
        if not cands:
            print(f"     {C_Y}لا مرشّح.{C_0} {C_D}ابحث في الفهرس برقم القانون "
                  f"وسنته، وسجّل الرابط يدويًا.{C_0}\n")
            continue
        for n, c in enumerate(cands, 1):
            flag = f"{C_G}★{C_0}" if c.strong else " "
            print(f"   {flag} {n}. {c.score:.2f}  {c.text[:70]}")
            print(f"        {C_D}{c.url}{C_0}")
            print(f"        {C_D}{' · '.join(c.reasons)}{C_0}")
        top = cands[0]
        if write and top.strong:
            ok, why = set_url(Path(sources_path), inst["key"], top.url, allowed)
            if ok:
                recorded += 1
                print(f"     {C_G}✓ سُجّل الرابط الأول.{C_0} {C_D}يبقى غير قابل "
                      f"للاستشهاد حتى تُسجَّل الجريدة، ويتحقق المستورد من "
                      f"العنوان من متن النص نفسه.{C_0}")
            else:
                print(f"     {C_R}✗ لم يُسجَّل:{C_0} {why}")
        elif write:
            why = ("المطابقة من سياق الصفحة لا من نص الرابط"
                   if top.from_context else "الترجيح دون العتبة القاطعة")
            print(f"     {C_Y}لم يُسجَّل آليًا{C_0} {C_D}— {why}. افتح الرابط "
                  f"وتأكد أنه التشريع بعينه.{C_0}")
        print(f"     python3 tools/ingest/ingest.py --set-provenance {inst['key']} \\")
        print(f"         --url \"{top.url}\" --gazette <العدد> --date YYYY-MM-DD\n")

    print(f"{C_D}{'─' * 60}{C_0}")
    if write:
        print(f"  سُجّل آليًا: {recorded} رابطًا (الترجيح القاطع وحده).")
    else:
        print(f"  {C_D}لم يُكتب شيء. للتسجيل الآلي للمرشّح القاطع (★):"
              f" --discover --write-urls{C_0}")
    print(f"  {C_D}المطابقة على نص الرابط لا على متن التشريع — والتحقق النهائي\n"
          f"  عند الاستيراد بمقارنة العنوان بالنص المُنزَّل.{C_0}\n")
    print(f"  ثم:  {C_B}python3 scripts/build-corpus.py{C_0}\n")
    return 0


def backend_warnings(plan: list[dict]) -> list[str]:
    """تنبيه مبكر عن خلفية استخراج ناقصة.

    الفهارس الرسمية تقدّم أكثر التشريعات بصيغة PDF، فبلا خلفية قراءة يفشل
    التحويل بعد التنزيل لا قبله. قوله هنا يوفّر عليك تنزيل عشرة ملفات لتكتشف
    أن أيًّا منها لن يُقرأ.
    """
    have = documents.available_backends()
    out = []
    staged_pdf = any(p["file"] and p["file"].suffix.lower() == ".pdf" for p in plan)
    if not have.get("pdf") and (staged_pdf or any(p["action"] == "fetch" for p in plan)):
        out.append("لا خلفية لقراءة PDF — وأكثر ما تقدّمه الفهارس الرسمية PDF."
                   + (" ملفات PDF مُجهَّزة لن تُقرأ. " if staged_pdf else " ")
                   + "ثبّتها:  sudo apt install poppler-utils")
    if not have.get("ocr") and staged_pdf:
        out.append("لا تعرّف ضوئي (OCR) — وPDF ممسوح ضوئيًا بلا طبقة نصية "
                   "سيُرفض:  sudo apt install tesseract-ocr tesseract-ocr-ara")
    return out


def run(cmd: list[str]) -> int:
    """تشغيل أداة من أدوات المستودع — بلا صدفة، والمخرجات تمر كما هي."""
    print(f"{C_D}$ {' '.join(cmd[1:])}{C_0}")
    return subprocess.run(cmd, cwd=str(ROOT), check=False).returncode  # noqa: S603


# ── الدورة ────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(
        description="بناء المدونة القانونية من المصادر الرسمية",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--sources", default=str(ROOT / "corpus/sources.yaml"))
    ap.add_argument("--only", nargs="*", metavar="KEY", help="اقتصار على مفاتيح بعينها")
    ap.add_argument("--plan", action="store_true", help="اعرض الخطة دون تنفيذ")
    ap.add_argument("--no-fetch", action="store_true", help="لا تنزيل — المُجهَّز فقط")
    ap.add_argument("--refresh", action="store_true", help="أعد التنزيل ولو كان مُجهَّزًا")
    ap.add_argument("--accept-low-confidence", action="store_true",
                    help="اقبل استخراجًا منخفض الثقة (لا يُنصح)")
    ap.add_argument("--force-unverified", action="store_true",
                    help="استورد رغم فشل مطابقة العنوان")
    ap.add_argument("--no-calibrate", action="store_true", help="لا تعايِر العتبة")
    ap.add_argument("--discover", nargs="*", metavar="URL",
                    help="استكشف روابط التشريعات الناقصة من فهرس رسمي "
                         "(الافتراضي: الفهارس المسجّلة في sources.yaml)")
    ap.add_argument("--write-urls", action="store_true",
                    help="مع --discover: سجّل الرابط الأول متى كان ترجيحه قاطعًا")
    args = ap.parse_args()

    src = yaml.safe_load(Path(args.sources).read_text(encoding="utf-8")) or {}
    cfg = src.get("ingest", {})
    staging = ROOT / cfg.get("staging_dir", "corpus/staging")
    staging.mkdir(parents=True, exist_ok=True)
    allowed = {d["host"].lower() for d in src.get("domains", [])}
    ua = cfg.get("user_agent", "airlock/1.0")
    timeout = int(cfg.get("request_timeout_sec", 30))

    instruments = src.get("instruments", [])
    if args.only:
        want = set(args.only)
        instruments = [i for i in instruments if i["key"] in want]
        if not instruments:
            print(f"{C_R}لا تشريع يطابق: {' '.join(args.only)}{C_0}", file=sys.stderr)
            return 2

    if args.discover is not None:
        print(f"\n{C_B}══ استكشاف روابط التشريعات من الفهارس الرسمية ══{C_0}\n")
        catalogs = args.discover or [c["url"] for c in src.get("catalogs", [])
                                     if (c.get("url") or "").strip()]
        return cmd_discover(src, catalogs, instruments, ua, timeout, allowed,
                            args.sources, write=args.write_urls)

    plan = survey(instruments, staging, refresh=args.refresh, fetch=not args.no_fetch)
    n_fetch = sum(p["action"] == "fetch" for p in plan)
    n_staged = sum(p["action"] == "staged" for p in plan)
    n_manual = sum(p["action"] == "manual" for p in plan)

    print(f"\n{C_B}══ بناء المدونة القانونية من المصادر الرسمية ══{C_0}")
    print(f"{C_D}السجل: {args.sources}   |   التجهيز: {staging}{C_0}\n")
    print(f"{C_B}١· الفحص{C_0}")
    for p in plan:
        i = p["inst"]
        mark = {"fetch": f"{C_G}↓{C_0}", "staged": f"{C_G}▣{C_0}",
                "manual": f"{C_Y}·{C_0}"}[p["action"]]
        what = {"fetch": f"تنزيل من {urlparse(p['url']).hostname}",
                "staged": f"من {p['file'].name}" if p["file"] else "",
                "manual": "لا رابط ولا ملف مُجهَّز"}[p["action"]]
        print(f"  {mark} {i['key']:<28} {what}")
        if p["gap"]:
            print(f"      {C_D}ينقص التوثيق: {'، '.join(p['gap'])} — "
                  f"يُستورد لكنه لا يُستشهد به{C_0}")
    print(f"\n  {n_fetch} للتنزيل · {n_staged} مُجهَّز · {n_manual} بانتظارك")
    for line in backend_warnings(plan):
        print(f"  {C_Y}⚠{C_0} {line}")
    print()

    if args.plan:
        print(f"{C_D}عرض خطة فقط — لم يُنفَّذ شيء. احذف --plan للتنفيذ.{C_0}\n")
        return 0

    # ── ٢· التنزيل ──
    records, fetch_failed = [], []
    if not n_fetch:
        why = "مُعطَّل بـ--no-fetch" if args.no_fetch else "لا رابط جاهزًا للتنزيل"
        print(f"{C_B}٢· التنزيل{C_0}  {C_D}{why}.{C_0}\n")
    else:
        print(f"{C_B}٢· التنزيل{C_0}")
        for p in (q for q in plan if q["action"] == "fetch"):
            key = p["inst"]["key"]
            try:
                rec = download(p["url"], key, staging, ua, timeout, allowed)
            except Exception as exc:  # noqa: BLE001
                print(f"  {C_R}✗{C_0} {key}\n      {C_D}{type(exc).__name__}: {exc}{C_0}")
                fetch_failed.append(key)
                p["action"] = "staged" if p["file"] else "manual"
                continue
            records.append(rec)
            p["file"] = staging / rec["file"]
            p["action"] = "staged"
            print(f"  {C_G}✓{C_0} {key:<28} {rec['format']}، "
                  f"{rec['bytes'] // 1024} ك.ب")
            if rec["hops"]:
                print(f"      {C_D}تحويلات (كلها داخل قائمة السماح): "
                      f"{len(rec['hops'])}{C_0}")
        if records:
            man = staging / "manifest.json"
            old = {}
            if man.exists():
                try:
                    old = {r["key"]: r for r in json.loads(man.read_text("utf-8"))}
                except ValueError:
                    pass
            old.update({r["key"]: r for r in records})
            man.write_text(json.dumps(list(old.values()), ensure_ascii=False, indent=2),
                           encoding="utf-8")
            print(f"  {C_D}سجل التنزيل (الرابط والبصمة وتاريخ الوصول): "
                  f"{man.relative_to(ROOT)}{C_0}")
        print()

    # ── ٣· التحويل إلى نص ──
    convert = [p for p in plan if p["action"] == "staged" and p["file"]
               and extract.unsupported_reason(p["file"]) is not None]
    if not convert:
        print(f"{C_B}٣· التحويل إلى نص{C_0}  {C_D}لا ملف يحتاج تحويلًا.{C_0}\n")
    else:
        print(f"{C_B}٣· التحويل إلى نص{C_0}")
        for p in convert:
            key = p["inst"]["key"]
            out, note = to_text(p["file"], accept_low=args.accept_low_confidence)
            if out is None:
                print(f"  {C_R}✗{C_0} {key:<28} {C_D}{note}{C_0}")
                p["action"] = "manual"
            else:
                print(f"  {C_G}✓{C_0} {key:<28} {C_D}{out.name} — {note}{C_0}")
        print()

    ready = [p for p in plan if p["action"] == "staged"]

    # ── ٤· الاستيراد ──
    ingest_rc = 0
    if ready:
        print(f"{C_B}٤· الاستيراد{C_0}")
        cmd = [sys.executable, str(ROOT / "tools/ingest/ingest.py"), "--from-staging",
               "--sources", args.sources, "--only", *[p["inst"]["key"] for p in ready]]
        if args.force_unverified:
            cmd.append("--force-unverified")
        ingest_rc = run(cmd)
    else:
        print(f"{C_Y}٤· لا شيء لاستيراده — لا ملف مُجهَّز لأي تشريع.{C_0}\n")

    # ── ٥· المعايرة ──
    db = ROOT / cfg.get("index_db", "corpus/index/corpus.db")
    if not args.no_calibrate and db.exists():
        print(f"\n{C_B}٥· معايرة عتبة التدقيق الدلالي{C_0}")
        # المعايرة ملك المدونة التي قيست منها: تُكتب بجوارها لا في مسار ثابت
        run([sys.executable, str(ROOT / "scripts/calibrate-threshold.py"),
             "--db", str(db), "--out", str(db.parent / "calibration.json"), "--write"])

    # ── ٦· ما بقي ──
    print(f"\n{C_B}٦· ما بقي عليك{C_0}")
    pending = [p for p in plan if p["action"] == "manual" or p["gap"]]
    if not pending:
        print(f"  {C_G}لا شيء — كل تشريع في السجل مستورد وموثَّق.{C_0}")
        print(f"  {C_D}راجع أسناد بنود العقود: "
              f"python3 tools/contracts/fill_sanad.py --status{C_0}")
    else:
        print(f"  {C_D}السكربت لا يخترع رابطًا ولا رقم جريدة. هذه هي الخطوات"
              f" التي تحتاج تصفّحك:{C_0}\n")
        for p in pending:
            i, key = p["inst"], p["inst"]["key"]
            print(f"  ── {i['title']} ({i['number']}/{i['year']})")
            if p["action"] == "manual" and not p["url"]:
                print(f"     {C_D}لا رابط مسجَّلًا له. ابحث عنه في "
                      f"legalaffairs.gov.bh أو mola.gov.bh برقمه وسنته.{C_0}")
            elif p["action"] == "manual":
                print(f"     {C_D}تعذّر تنزيله من الرابط المسجَّل. نزّله يدويًا "
                      f"إلى:{C_0}")
                print(f"     {staging.relative_to(ROOT)}/{key}.html   "
                      f"{C_D}(أو .pdf أو .docx — تُحوَّل تلقائيًا){C_0}")
            else:
                print(f"     {C_D}مستورد، لكن لا يُستشهد به: ينقصه "
                      f"{'، '.join(p['gap'])}.{C_0}")
            if p["gap"]:
                print(f"     python3 tools/ingest/ingest.py --set-provenance {key} \\")
                print(f"         --url \"https://…\" --gazette <العدد> --date YYYY-MM-DD")
            print(f"     {C_D}ثم: python3 scripts/build-corpus.py --only {key}{C_0}\n")

    print(f"{C_D}{'─' * 60}{C_0}")
    print(f"  نُزِّل: {len(records)}   استُورد منه: {len(ready)}   "
          f"بانتظار توثيق أو تنزيل: {len(pending)}")
    if fetch_failed:
        print(f"  {C_Y}فشل تنزيل: {'، '.join(fetch_failed)}{C_0}")
    if db.exists():
        run([sys.executable, str(ROOT / "tools/corpus/corpus_cli.py"),
             "--db", str(db), "stats"])
    return 0 if ready and ingest_rc == 0 and not fetch_failed else 1


if __name__ == "__main__":
    sys.exit(main())
