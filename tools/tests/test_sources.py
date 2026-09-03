"""اختبارات سجل المصادر وتسجيل الروابط."""
import importlib.util
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import yaml  # noqa: E402

spec = importlib.util.spec_from_file_location("ing", ROOT / "tools/ingest/ingest.py")
ing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ing)

FAIL = 0
TMP = Path(tempfile.mkdtemp())
SRC = ROOT / "corpus/sources.yaml"
CFG = yaml.safe_load(SRC.read_text(encoding="utf-8"))
ALLOWED = {d["host"].lower() for d in CFG["domains"]}


def check(name, got, want):
    global FAIL
    if got == want:
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}\n      المتوقع: {want!r}\n      الناتج : {got!r}")


def fresh() -> Path:
    p = TMP / "sources.yaml"
    shutil.copy(SRC, p)
    return p


print("\n── بنية السجل ──")
keys = [i["key"] for i in CFG["instruments"]]
check("لا مفاتيح مكررة", len(keys), len(set(keys)))
check("كل تشريع له حقل url", all("url" in i for i in CFG["instruments"]), True)
check("كل تشريع له نطاق ممارسة",
      all(i.get("practice_areas") for i in CFG["instruments"]), True)
check("كل تشريع بنوع معروف",
      all(i["type"] in ("law", "dl", "dec", "ord", "reg") for i in CFG["instruments"]), True)

print("\n── سلامة ما وُثّق ──")
# الروابط لا تأتي مني: أُدخلها صاحب المكتب من المصدر الرسمي. فالثابت المطلوب
# ليس «لا شيء مملوء» بل «ما مُلئ فهو مكتمل ومن نطاق رسمي».
documented = [i for i in CFG["instruments"] if not ing.provenance_gap(i)]
partial = [i["key"] for i in CFG["instruments"]
           if ing.provenance_gap(i) and any(
               str(i.get(k) or "").strip() for k in ("url", "gazette_issue", "gazette_date"))]
check("لا توثيق نصف مكتمل", partial, [])
from urllib.parse import urlparse  # noqa: E402
check("كل رابط موثّق من نطاق رسمي",
      [i["key"] for i in documented
       if (urlparse(i["url"]).hostname or "").lower() not in ALLOWED], [])
check("كل تاريخ جريدة بصيغة صحيحة",
      [i["key"] for i in documented
       if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(i["gazette_date"]))], [])
check("verified يبقى false في السجل — يُحسم عند الاستيراد",
      all(i.get("verified") is False for i in CFG["instruments"]), True)

print("\n── حواجز تسجيل الرابط ──")
p = fresh()
for name, key, url in [
    ("نطاق غير رسمي يُرفض", "civil-code", "https://example.com/law"),
    ("نطاق مشابه يُرفض", "civil-code", "https://legislation.bh.evil.com/x"),
    ("بروتوكول ftp يُرفض", "civil-code", "ftp://legislation.bh/x"),
    ("مفتاح مجهول يُرفض", "band-wahmi", "https://legislation.bh/x"),
    ("رابط بعلامة اقتباس يُرفض", "civil-code", 'https://legislation.bh/a"b'),
]:
    ok, _ = ing.set_url(p, key, url, ALLOWED)
    check(name, ok, False)
check("لم يتغير الملف بعد كل الرفض", p.read_text(encoding="utf-8"),
      SRC.read_text(encoding="utf-8"))

print("\n── التسجيل الناجح ──")
p = fresh()
before = p.read_text(encoding="utf-8")
URL = "https://legislation.bh/tafaseel/9999"
ok, why = ing.set_url(p, "civil-code", URL, ALLOWED)
check("نطاق رسمي يُقبل", ok, True)
after = p.read_text(encoding="utf-8")
check("الرابط كُتب", f'url: "{URL}"' in after, True)
check("التعليقات محفوظة", after.count("#"), before.count("#"))
check("سطر واحد فقط تغيّر",
      sum(1 for a, b in zip(before.splitlines(), after.splitlines()) if a != b), 1)
check("عدد الأسطر ثابت", len(after.splitlines()), len(before.splitlines()))
reloaded = yaml.safe_load(after)
check("YAML صالح بعد الكتابة", reloaded is not None, True)
check("الرابط يُقرأ",
      next(i["url"] for i in reloaded["instruments"] if i["key"] == "civil-code"), URL)
before_urls = {i["key"] for i in CFG["instruments"] if (i.get("url") or "").strip()}
check("بقية التشريعات لم تتأثر",
      {i["key"] for i in reloaded["instruments"] if (i.get("url") or "").strip()},
      before_urls | {"civil-code"})

print("\n── الكتابة فوق رابط موجود ──")
ok, _ = ing.set_url(p, "civil-code", "https://www.legislation.bh/x/1", ALLOWED)
check("تُقبل", ok, True)
r2 = yaml.safe_load(p.read_text(encoding="utf-8"))
check("استُبدل لا أُضيف",
      next(i["url"] for i in r2["instruments"] if i["key"] == "civil-code"),
      "https://www.legislation.bh/x/1")
check("عدد الأسطر ما زال ثابتًا",
      len(p.read_text(encoding="utf-8").splitlines()), len(before.splitlines()))

print("\n── كل نطاقات السماح تُقبل ──")
for host in sorted(ALLOWED):
    q = fresh()
    ok, _ = ing.set_url(q, "arbitration", f"https://{host}/law", ALLOWED)
    check(f"{host}", ok, True)


print("\n── توثيق الجريدة الرسمية ──")
# الجريدة هي المرجع النهائي الملزم: القانون لا ينفذ إلا بالنشر فيها، فرقم
# العدد وتاريخه هما ما يثبت أن النص المستورد هو النافذ.
check("كل تشريع له حقلا الجريدة",
      all("gazette_issue" in i and "gazette_date" in i for i in CFG["instruments"]), True)
check("التوثيق الموجود مكتمل لا جزئي",
      [i["key"] for i in CFG["instruments"] if ing.provenance_gap(i)
       and not all(not str(i.get(k) or "").strip()
                   for k in ("url", "gazette_issue", "gazette_date"))], [])
check("نقص التوثيق يُرصد كاملًا",
      ing.provenance_gap({"url": "", "gazette_issue": "", "gazette_date": ""}),
      ["رابط المصدر الرسمي", "رقم عدد الجريدة الرسمية", "تاريخ النشر في الجريدة"])
check("التوثيق الكامل بلا نقص",
      ing.provenance_gap({"url": "https://lloc.gov.bh/x", "gazette_issue": "3062",
                          "gazette_date": "2012-07-26"}), [])
check("نقص جزئي يُرصد",
      ing.provenance_gap({"url": "https://lloc.gov.bh/x", "gazette_issue": "3062",
                          "gazette_date": ""}), ["تاريخ النشر في الجريدة"])

print("\n── كتابة حقول التوثيق ──")
p2 = fresh()
before2 = p2.read_text(encoding="utf-8")
ok, why = ing.set_fields(p2, "civil-code",
                         {"gazette_issue": "2501", "gazette_date": "2001-09-06"})
check("تُكتب", ok, True)
after2 = p2.read_text(encoding="utf-8")
check("التعليقات محفوظة", after2.count("#"), before2.count("#"))
check("عدد الأسطر ثابت", len(after2.splitlines()), len(before2.splitlines()))
r = yaml.safe_load(after2)
ci = next(i for i in r["instruments"] if i["key"] == "civil-code")
check("العدد كُتب", str(ci["gazette_issue"]), "2501")
check("التاريخ كُتب", str(ci["gazette_date"]), "2001-09-06")
before_doc = {i["key"] for i in CFG["instruments"] if not ing.provenance_gap(i)}
check("بقية التشريعات لم تتأثر",
      {i["key"] for i in r["instruments"] if not ing.provenance_gap(i)}, before_doc)
ok, _ = ing.set_fields(p2, "civil-code", {"gazette_issue": 'a"b'})
check("قيمة بعلامة اقتباس تُرفض", ok, False)

print("\n── نطاقات المصادر الرسمية الجديدة ──")
for host in ("lloc.gov.bh", "mola.gov.bh", "mia.gov.bh", "ppb.gov.bh", "nuwab.bh"):
    check(f"{host} في قائمة السماح", host in ALLOWED, True)
check("للجريدة الرسمية دور خاص",
      any(d.get("role") == "gazette" for d in CFG["domains"]), True)


print("\n── تتبّع التعديلات ──")
# أخطر عطب لا تلتقطه أي بوابة: المادة موجودة ورقمها صحيح ونصها مطابق لما
# استُورد — لكنه النص الأصلي لا النافذ، والمحكمة تطبّق النافذ.
from lib.corpus import amendment_warning  # noqa: E402

check("كل تشريع له حقلا التعديل",
      all("amendments" in i and "consolidated" in i for i in CFG["instruments"]), True)
check("لا تشريع موسوم مدمجًا بلا أساس",
      [i["key"] for i in CFG["instruments"] if i.get("consolidated")], [])


class Row(dict):
    def keys(self): return super().keys()
    def __getitem__(self, k): return super().__getitem__(k)


import json as _json  # noqa: E402
check("نص بلا تعديلات: لا تنبيه",
      amendment_warning(Row(amendments="[]", consolidated=0)), None)
check("نص مدمج: لا تنبيه",
      amendment_warning(Row(amendments=_json.dumps([{"type": "law", "number": 1,
                                                     "year": 2020}]), consolidated=1)),
      None)
w = amendment_warning(Row(amendments=_json.dumps(
    [{"type": "law", "number": 31, "year": 2014},
     {"type": "dl", "number": 59, "year": 2018}]), consolidated=0))
check("نص غير مدمج: تنبيه", bool(w), True)
check("التنبيه يذكر العدد", "(2)" in (w or ""), True)
check("التنبيه يسمّي التعديلات",
      "law 31/2014" in (w or "") and "dl 59/2018" in (w or ""), True)
check("تعديلات معطوبة لا تُسقط الأداة",
      amendment_warning(Row(amendments="{ليس json", consolidated=0)), None)

lab = next(i for i in CFG["instruments"] if i["key"] == "labour-private-sector")
check("قانون العمل له تعديلات مسجّلة", len(lab["amendments"]) >= 3, True)
check("وهو غير مدمج", lab["consolidated"], False)
check("كل تعديل بنوع ورقم وسنة",
      all({"type", "number", "year"} <= set(a) for a in lab["amendments"]), True)

print(f"\n{'✓ كل الاختبارات ناجحة' if not FAIL else f'✗ {FAIL} اختبار فاشل'}\n")
sys.exit(1 if FAIL else 0)
