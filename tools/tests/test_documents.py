"""اختبارات معالجة المستندات — الأمان أولًا ثم الدقة.

Hostile input first: these files are what an opposing party could send.
"""
import io
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import documents as doc  # noqa: E402

FAIL = 0
TMP = Path(tempfile.mkdtemp())


def check(name, got, want):
    global FAIL
    if got == want:
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}\n      المتوقع: {want!r}\n      الناتج : {got!r}")


def raises(name, fn, needle=""):
    global FAIL
    try:
        fn()
    except doc.DocumentError as e:
        if needle and needle not in str(e):
            FAIL += 1
            print(f"  ✗ {name}\n      رُفض لكن بسبب آخر: {e}")
        else:
            print(f"  ✓ {name}")
        return
    except Exception as e:  # noqa: BLE001
        FAIL += 1
        print(f"  ✗ {name}\n      استثناء غير متوقع: {type(e).__name__}: {e}")
        return
    FAIL += 1
    print(f"  ✗ {name}\n      لم يُرفض — عطب أمني")


def write(name: str, data: bytes) -> Path:
    p = TMP / name
    p.write_bytes(data)
    return p


def docx_with(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in members.items():
            z.writestr(n, d)
    return buf.getvalue()


P = ('<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
     '<w:p><w:r><w:t>عقد عمل محدد المدة</w:t></w:r></w:p>'
     '<w:p><w:r><w:t>يلتزم الطرف الأول بأداء أجر شهري قدره 800 دينار.</w:t></w:r></w:p>'
     '</w:body></w:document>').encode()

print("\n══ الأمان ══")
print("\n── كشف الصيغة بالتوقيع لا بالامتداد ──")
p = write("contract.txt", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
check("PDF متنكر في .txt يُكشف", doc.detect_format(p), "pdf")
p = write("evidence.pdf", docx_with({"word/document.xml": P}))
check("DOCX متنكر في .pdf يُكشف", doc.detect_format(p), "docx")
r = doc.extract(write("note.pdf", "اتفاق ودي بين الطرفين على إنهاء النزاع.".encode()))
check("النص المتنكر يُعالج بمحتواه", r.fmt, "text")
check("عدم تطابق الامتداد يُبلَّغ",
      any("لا يطابق المحتوى" in w for w in r.warnings), True)

print("\n── قنابل الضغط والانفلات من المسار ──")
raises("قنبلة ضغط تُرفض",
       lambda: doc.extract(write("bomb.docx", docx_with(
           {"word/document.xml": P, "payload.bin": b"\0" * (30 * 1024 * 1024)}))),
       "ضغط")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("word/document.xml", P)
    z.writestr("../../../etc/cron.d/evil", b"* * * * * root sh -c evil")
raises("انفلات من المسار يُرفض",
       lambda: doc.extract(write("slip.docx", buf.getvalue())), "مسار خطر")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("word/document.xml", P)
    for i in range(3_100):
        z.writestr(f"m{i}.txt", b"x")
raises("عدد أعضاء مفرط يُرفض",
       lambda: doc.extract(write("many.docx", buf.getvalue())), "عنصرًا")

print("\n── هجمات XML ──")
XXE = ('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
       '<w:document xmlns:w="x"><w:body><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p>'
       '</w:body></w:document>').encode()
raises("كيان خارجي (XXE) يُرفض",
       lambda: doc.extract(write("xxe.docx", docx_with({"word/document.xml": XXE}))),
       "XXE")
LOL = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa">'
       '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
       '<w:document xmlns:w="x"><w:body><w:p>&b;</w:p></w:body></w:document>').encode()
raises("تفجّر الكيانات يُرفض",
       lambda: doc.extract(write("lol.docx", docx_with({"word/document.xml": LOL}))))

print("\n── صيغ لا تُفتح ──")
raises("Office قديم (ماكرو محتمل) لا يُفتح",
       lambda: doc.extract(write("old.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600)),
       "ماكرو")
raises("ملف فارغ", lambda: doc.extract(write("empty.pdf", b"")), "فارغ")
raises("صيغة مجهولة", lambda: doc.extract(write("x.bin", b"\x07\x08\x09\xfe" * 300)))

print("\n══ الدقة ══")
print("\n── DOCX بالمكتبة القياسية ──")
r = doc.extract(write("ok.docx", docx_with({"word/document.xml": P})))
check("النص مستخرج", "عقد عمل محدد المدة" in r.text, True)
check("الفقرة الثانية", "800 دينار" in r.text, True)
check("مقبول", r.ok, True)
check("الطريقة معلنة", "مكتبة قياسية" in r.method, True)
check("البصمة محسوبة", len(r.sha256), 64)

print("\n── قياس الجودة ──")
check("نص فارغ ⇒ ثقة صفر", doc.assess("", "pdf")[0], 0.0)
conf, w = doc.assess("ي ل ت ز م ا ل ط ر ف ا ل أ و ل ب أ د ا ء أ ج ر ش ه ر ي "
                     "ق د ر ه ث م ا ن م ا ئ ة د ي ن ا ر ل ك ل ش ه ر م ي لادي", "pdf")
check("حروف مفصولة تُرصد", any("مفصولة" in x for x in w), True)
check("حروف مفصولة تخفض الثقة", conf < 0.7, True)
conf, w = doc.assess("ﺍﻟﻌﻘﺪ ﺍﻟﻤﺒﺮﻡ ﺑﻴﻦ ﺍﻟﻄﺮﻓﻴﻦ ﻳﻠﺰﻡ ﻛﻼ ﻣﻨﻬﻤﺎ ﺑﺄﺩﺍﺀ ﺍﻟﺘﺰﺍﻣﺎﺗﻪ", "pdf")
check("أشكال العرض تُرصد", any("أشكال العرض" in x for x in w), True)
conf, w = doc.assess("ØªØ¬Ø±Ø¨Ø© Ù†Øµ Ù…Ø´ÙˆÙ‡ ØªÙ…Ø§Ù…Ø§", "pdf")
check("نص بلا عربية يُرصد", any("نسبة الحروف العربية" in x for x in w), True)
conf, w = doc.assess("العقد المبرم بين الطرفين ملزم لهما", "jpeg")
check("مصدر صورة يُنبَّه عليه", any("التعرّف الضوئي" in x for x in w), True)
check("صورة سليمة تبقى مقبولة", conf >= 0.6, True)

print("\n── تطبيع أشكال العرض ──")
r = doc.extract(write("pres.docx", docx_with({"word/document.xml":
    ('<?xml version="1.0"?><w:document xmlns:w="x"><w:body><w:p><w:r><w:t>'
     'ﺍﻟﻌﻘﺪ ﺍﻟﻤﺒﺮﻡ ﺑﻴﻦ ﺍﻟﻄﺮﻓﻴﻦ</w:t></w:r></w:p></w:body></w:document>').encode()})))
check("طُبّعت إلى حروف منطقية", "العقد" in r.text, True)

print("\n── الخلفيات المتاحة ──")
b = doc.available_backends()
check("تقرير الخلفيات مكتمل", set(b), {"pdf", "ocr", "legacy_doc"})
for k, v in b.items():
    print(f"      {k:<12} {v or '— غير مثبّت'}")

print(f"\n{'✓ كل الاختبارات ناجحة' if not FAIL else f'✗ {FAIL} اختبار فاشل'}\n")
sys.exit(1 if FAIL else 0)
