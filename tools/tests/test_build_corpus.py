"""اختبارات سكربت بناء المدونة — التنزيل والتحويلات وترحيل المخزن.

The download path is the one place in this repo that reaches the network, so
its guards are tested against a real local server rather than mocks: an
allowlist that only holds before the first redirect is not an allowlist.
"""
import http.server
import importlib.util
import os
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

spec = importlib.util.spec_from_file_location("bc", ROOT / "scripts/build-corpus.py")
bc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bc)

FAIL = 0
TMP = Path(tempfile.mkdtemp())


def check(name, got, want):
    global FAIL
    ok = got == want
    FAIL += not ok
    print(f"  {'✓' if ok else '✗'} {name}" + ("" if ok else f"\n      كان: {got!r}"))


def raises(name, fn, exc_type, needle=""):
    global FAIL
    try:
        fn()
    except exc_type as exc:
        ok = needle in str(exc)
        FAIL += not ok
        print(f"  {'✓' if ok else '✗'} {name}" + ("" if ok else f"\n      كان: {exc}"))
    except Exception as exc:  # noqa: BLE001
        FAIL += 1
        print(f"  ✗ {name}\n      استثناء آخر: {type(exc).__name__}: {exc}")
    else:
        FAIL += 1
        print(f"  ✗ {name}\n      لم يُرفض")


# ── خادم محلي يمثّل موقعًا رسميًا ──────────────────────────────────────
BODY = ("<html><head><title>قانون تجريبي</title></head><body>"
        "<p>مادة (1) نص المادة الأولى.</p></body></html>").encode()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/redirect-out":
            self.send_response(302)
            self.send_header("Location", "https://evil.example.com/law")
            self.end_headers()
        elif self.path == "/redirect-in":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/law")
            self.end_headers()
        elif self.path == "/pdf":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")   # ترويسة كاذبة عمدًا
            self.end_headers()
            self.wfile.write(b"%PDF-1.4\n% test\n")
        elif self.path == "/catalog":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(CATALOG.encode())
        elif self.path == "/huge":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"x" * 4096)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(BODY)

    def log_message(self, *a):
        pass


os.environ["no_proxy"] = "*"
os.environ["NO_PROXY"] = "*"
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_port}"
ALLOWED = {"127.0.0.1"}
STAGING = TMP / "staging"
STAGING.mkdir(parents=True, exist_ok=True)


def get(path, key, allowed=ALLOWED, timeout=10):
    return bc.download(f"{BASE}{path}", key, STAGING, "test/1.0", timeout, allowed)


print("\n── قائمة السماح ──")
raises("نطاق خارج القائمة يُرفض قبل الطلب",
       lambda: bc.download("https://evil.example.com/x", "k", STAGING, "t", 5, ALLOWED),
       PermissionError, "خارج قائمة السماح")
raises("تحويلة إلى نطاق غير مسموح تُرفض",
       lambda: get("/redirect-out", "k1"), PermissionError, "تحويلة إلى نطاق")
rec = get("/redirect-in", "k2")
check("تحويلة داخل القائمة تمر", rec["status"], 200)
check("وتُسجَّل التحويلة", len(rec["hops"]), 1)

print("\n── السجل المرافق ──")
rec = get("/law", "labour")
check("الصيغة من البايتات", rec["format"], "html")
check("الامتداد يتبع الصيغة", rec["file"], "labour.html")
check("البصمة مسجّلة", len(rec["sha256"]), 64)
check("تاريخ الوصول مسجّل", rec["retrieved_at"].startswith("20"), True)
check("الرابط الأصلي مسجّل", rec["url"].endswith("/law"), True)
check("الملف كُتب فعلًا", (STAGING / "labour.html").read_bytes(), BODY)

# الترويسة تقول html والبايتات تقول pdf — البايتات هي الحكم
rec = get("/pdf", "sniff")
check("ترويسة كاذبة لا تخدع الكاشف", rec["format"], "pdf")
check("الامتداد من الكشف لا من الترويسة", rec["file"], "sniff.pdf")
check("لا يبقى ملف مؤقت", sorted(p.name for p in STAGING.glob(".*")), [])

print("\n── الحدود ──")
old_max = bc.MAX_DOWNLOAD_BYTES
bc.MAX_DOWNLOAD_BYTES = 100
raises("تجاوز الحجم يُرفض", lambda: get("/huge", "big"), ValueError, "يتجاوز")
bc.MAX_DOWNLOAD_BYTES = old_max

print("\n── الفحص وتصنيف الحالة ──")
insts = [
    {"key": "labour", "url": f"{BASE}/law", "gazette_issue": "1", "gazette_date": "2012-01-01"},
    {"key": "nourl", "url": "", "gazette_issue": "", "gazette_date": ""},
]
plan = bc.survey(insts, STAGING, refresh=False, fetch=True)
check("مُجهَّز مسبقًا لا يُنزَّل ثانية", plan[0]["action"], "staged")
check("بلا رابط ولا ملف: يدوي", plan[1]["action"], "manual")
check("نقص التوثيق مُعلن", plan[1]["gap"], ["رابط", "عدد الجريدة", "تاريخ النشر"])
plan = bc.survey(insts, STAGING, refresh=True, fetch=True)
check("--refresh يعيد التنزيل", plan[0]["action"], "fetch")
plan = bc.survey(insts, STAGING, refresh=True, fetch=False)
check("--no-fetch يمنع التنزيل", plan[0]["action"], "staged")

print("\n── التحويل إلى نص ──")
p, note = bc.to_text(STAGING / "labour.html", accept_low=False)
check("ملف نصي يمر كما هو", p.name, "labour.html")
bad = STAGING / "bad.pdf"
bad.write_bytes(b"%PDF-1.4\n")
out, why = bc.to_text(bad, accept_low=False)
check("استخراج فاشل لا يكتب نصًا", out, None)
check("والسبب معلن", bool(why), True)
check("ولا يُترك ملف نصي مضلّل", (STAGING / "bad.txt").exists(), False)

print("\n── الاستكشاف من فهرس رسمي ──")
CATALOG = ("<html><body><ul>"
           "<li><a href='/L/K3612'>قانون رقم (\u0663\u0666) لسنة \u0662\u0660\u0661\u0662 "
           "بإصدار قانون العمل في القطاع الأهلي</a></li>"
           "<li><a href='/L/K1901'>مرسوم بقانون رقم (19) لسنة 2001 بإصدار القانون المدني</a></li>"
           "<li><a href='/L/K3614'>قانون رقم (36) لسنة 2014 في شأن آخر تمامًا</a></li>"
           "<li><a href='javascript:void(0)'>افتح</a></li>"
           "<li><a href='https://mirror.example.com/civil'>القانون المدني</a></li>"
           "</ul></body></html>")

from lib import discover  # noqa: E402

found = discover.links(CATALOG, f"{BASE}/ElectronicLibrary")
check("javascript: لا يُلتقط", all("javascript" not in x.url for x in found), True)
check("روابط خارج المضيف تُستبعد",
      all("mirror.example.com" not in x.url for x in found), True)
check("الروابط النسبية تُحوَّل مطلقة",
      sorted(x.url for x in found), [f"{BASE}/L/K1901", f"{BASE}/L/K3612", f"{BASE}/L/K3614"])

INSTS = [
    {"key": "labour", "type": "law", "number": 36, "year": 2012,
     "title": "قانون العمل في القطاع الأهلي"},
    {"key": "civil", "type": "dl", "number": 19, "year": 2001, "title": "القانون المدني"},
    {"key": "ghost", "type": "law", "number": 99, "year": 1999, "title": "قانون لا وجود له"},
]
hits = discover.match(INSTS, found)
check("الأرقام العربية الهندية تُطابق", hits["labour"][0].url, f"{BASE}/L/K3612")
check("والمرشّح الأول قاطع", hits["labour"][0].strong, True)
check("النوع يميّز المرسوم بقانون", hits["civil"][0].url, f"{BASE}/L/K1901")
check("رقم صحيح بسنة خاطئة لا يُرشَّح",
      any(c.url.endswith("K3614") for c in hits["labour"]), False)
check("تشريع لا وجود له في الفهرس: لا مرشّح", "ghost" in hits, False)

# ── الدورة كاملة عبر الشبكة المحلية، مع الكتابة في السجل ──
import re as _re  # noqa: E402

SRC = TMP / "src.yaml"
SRC.write_text(
    "domains:\n  - host: 127.0.0.1\n    role: primary\n"
    f"catalogs:\n  - url: \"{BASE}/catalog\"\n"
    "instruments:\n"
    "  - key: civil-code\n    type: dl\n    number: 19\n    year: 2001\n"
    "    title: القانون المدني\n    url: \"\"\n"
    "    gazette_issue: \"\"\n    gazette_date: \"\"\n    verified: false\n",
    encoding="utf-8")
import yaml  # noqa: E402

cfg = yaml.safe_load(SRC.read_text(encoding="utf-8"))
rc = bc.cmd_discover(cfg, [f"{BASE}/catalog"], cfg["instruments"], "t/1", 10,
                     {"127.0.0.1"}, str(SRC), write=True)
check("الدورة تنجح", rc, 0)
written = SRC.read_text(encoding="utf-8")
check("سُجّل الرابط القاطع في السجل", f'url: "{BASE}/L/K1901"' in written, True)
check("ولم يُلمس التوثيق — يبقى غير قابل للاستشهاد",
      _re.search(r'gazette_issue: ""', written) is not None, True)

# فهرس خارج قائمة السماح لا يُقرأ أصلًا
rc = bc.cmd_discover(cfg, ["https://evil.example.com/list"], cfg["instruments"],
                     "t/1", 10, {"127.0.0.1"}, str(SRC), write=False)
check("فهرس خارج قائمة السماح يُرفض", rc, 1)


print("\n── ترحيل مخزن قديم ──")
# مدونة بُنيت بنسخة أقدم: `CREATE TABLE IF NOT EXISTS` لا يضيف أعمدة لجدول
# قائم، فبلا ترحيل يسقط أول بحث برسالة sqlite غامضة.
from lib.corpus import Corpus  # noqa: E402

old_db = TMP / "old.db"
con = sqlite3.connect(old_db)
con.executescript("""
CREATE TABLE instruments (id TEXT PRIMARY KEY, key TEXT NOT NULL, type TEXT NOT NULL,
  number TEXT NOT NULL, year TEXT NOT NULL, title TEXT NOT NULL, source_url TEXT,
  source_domain TEXT, retrieved_at TEXT NOT NULL, sha256 TEXT NOT NULL,
  verified INTEGER NOT NULL DEFAULT 0);
CREATE TABLE articles (instrument_id TEXT NOT NULL, article_key TEXT NOT NULL,
  number TEXT NOT NULL, bis INTEGER NOT NULL DEFAULT 0, label TEXT NOT NULL,
  text TEXT NOT NULL, PRIMARY KEY (instrument_id, article_key));
CREATE VIRTUAL TABLE articles_fts USING fts5(body, instrument_id UNINDEXED,
  article_key UNINDEXED, tokenize='unicode61');
INSERT INTO instruments VALUES ('law:1/2000','k','law','1','2000','قانون',NULL,NULL,
  '2026-01-01T00:00:00+00:00','x',1);
""")
con.commit()
con.close()
c = Corpus(old_db)
cols = {r[1] for r in c.db.execute("PRAGMA table_info(instruments)")}
check("العمود الناقص أُضيف", "consolidated" in cols and "source_tier" in cols, True)
check("الإحصاء يعمل بعد الترحيل", c.stats()["instruments"], 1)
check("والبيانات القديمة باقية", c.instrument("law:1/2000")["title"], "قانون")
c.close()
check("الترحيل لا يتكرر", Corpus(old_db)._migrate(), [])

srv.shutdown()
print(f"\n{'✓ كل الاختبارات ناجحة' if not FAIL else f'✗ {FAIL} اختبار فاشل'}\n")
sys.exit(1 if FAIL else 0)
