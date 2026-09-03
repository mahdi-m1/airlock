"""اختبارات إصدار Word — البنية والاتجاه العربي وترتيب المخطط."""
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import documents as doc  # noqa: E402
from lib.docx_writer import Style, parse_blocks, write_docx  # noqa: E402

FAIL = 0
TMP = Path(tempfile.mkdtemp())
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def check(name, got, want):
    global FAIL
    if got == want:
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}\n      المتوقع: {want!r}\n      الناتج : {got!r}")


MD = """# مذكرة قانونية

**القضية:** ع/2024/118

## أولًا: الوقائع
أُنهيت الخدمة في 2024/06/30 بأجر 800 دينار.

> يقع باطلًا كل فصل تعسفي.

## رابعًا: الطلبات
1. إلزام المدعى عليها بمبلغ (9,600) دينار.
2. المصروفات وأتعاب المحاماة.

- مستند أول
---
| الطرف | الصفة |
|---|---|
| أحمد | مدعٍ |
"""
OUT = write_docx(MD, TMP / "m.docx", title="مذكرة اختبار",
                 draft_notice="مسودة — تتطلب اعتماد محامٍ مقيّد.")
with zipfile.ZipFile(OUT) as z:
    NAMES = z.namelist()
    PARTS = {n: z.read(n) for n in NAMES}
DOCXML = PARTS["word/document.xml"].decode()

print("\n── بنية الحزمة ──")
check("الأرشيف سليم", zipfile.ZipFile(OUT).testzip(), None)
check("[Content_Types].xml أول عنصر", NAMES[0], "[Content_Types].xml")
for part in ("_rels/.rels", "word/document.xml", "word/styles.xml",
             "word/settings.xml", "word/_rels/document.xml.rels", "docProps/core.xml"):
    check(f"الجزء {part}", part in NAMES, True)

print("\n── صحة XML ──")
for n, data in PARTS.items():
    try:
        ET.fromstring(data)
        ok = True
    except ET.ParseError:
        ok = False
    check(f"XML سليم: {n}", ok, True)

print("\n── العلاقات تُحل ──")
R = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
for rel, base in (("_rels/.rels", ""), ("word/_rels/document.xml.rels", "word/")):
    for r in ET.fromstring(PARTS[rel]).findall(R):
        check(f"{r.get('Id')} في {rel}", base + r.get("Target") in NAMES, True)

print("\n── الاتجاه العربي ──")
# ثلاثتها إلزامية: بلا أيٍّ منها يُفتح الملف ويُطبع بمحاذاة يسار
check("w:bidi على الفقرات", "<w:bidi/>" in DOCXML, True)
check("w:rtl على التشغيلات", "<w:rtl/>" in DOCXML, True)
check("w:szCs (مقاس الكتابة المركّبة)", "w:szCs" in DOCXML, True)
check("w:rFonts w:cs (خط عربي)", 'w:cs="Traditional Arabic"' in DOCXML, True)
check("bidi على المقطع", "<w:bidi/></w:sectPr>" in DOCXML.replace("<w:docGrid", "X<w:docGrid")
      or "<w:bidi/><w:docGrid" in DOCXML, True)
styles = PARTS["word/styles.xml"].decode()
check("الافتراضيات ترث rtl", "<w:rtl/>" in styles, True)
check("لغة الوثيقة ar-BH", 'w:bidi="ar-BH"' in styles, True)

print("\n── ترتيب عناصر المخطط ──")
# OOXML يعرّف CT_PPr و CT_RPr تسلسلًا لا مجموعة. الخروج عنه يجعل الملف
# غير قابل للتحميل أصلًا — وهو العطب الذي كسر أول نسخة من هذا الكاتب.
PPR_SEQ = ["keepNext", "pBdr", "bidi", "spacing", "ind", "jc"]
RPR_SEQ = ["rFonts", "b", "bCs", "color", "sz", "szCs", "rtl", "lang"]


def ordered(xml_frag: str, seq: list[str]) -> bool:
    tags = re.findall(r"<w:(\w+)[ /]", xml_frag)
    idx = [seq.index(t) for t in tags if t in seq]
    return idx == sorted(idx)


bad_p = [p for p in re.findall(r"<w:pPr>(.*?)</w:pPr>", DOCXML) if not ordered(p, PPR_SEQ)]
check("ترتيب w:pPr يتبع التسلسل", bad_p, [])
bad_r = [r for r in re.findall(r"<w:rPr>(.*?)</w:rPr>", DOCXML) if not ordered(r, RPR_SEQ)]
check("ترتيب w:rPr يتبع التسلسل", bad_r, [])
check("ترتيب w:rPr في الأنماط",
      all(ordered(r, RPR_SEQ) for r in re.findall(r"<w:rPr>(.*?)</w:rPr>", styles, re.S)), True)

print("\n── تحليل Markdown ──")
b = dict((k, 0) for k in ("h1", "h2", "p", "num", "bul", "quote", "rule", "row"))
for kind, _ in parse_blocks(MD):
    b[kind] = b.get(kind, 0) + 1
check("عنوان رئيسي", b["h1"], 1)
check("عناوين فرعية", b["h2"], 2)
check("بنود مرقّمة", b["num"], 2)
check("بند نقطي", b["bul"], 1)
check("اقتباس", b["quote"], 1)
check("فاصل", b["rule"], 1)
check("صفوف جدول (بلا سطر الفاصل)", b["row"], 2)

print("\n── المحتوى يصل كاملًا ──")
r = doc.extract(OUT)
check("يُقرأ كـdocx", r.fmt, "docx")
check("ثقة تامة", r.confidence >= 0.9, True)
for probe in ("مذكرة قانونية", "مسودة", "ع/2024/118", "9,600", "2024/06/30",
              "المصروفات", "مستند أول", "أحمد"):
    check(f"«{probe}»", probe in r.text, True)
check("الترقيم حرفي لا تلقائي", "1. إلزام" in r.text, True)

print("\n── ترويسة المسودة ──")
check("تظهر في الوثيقة", "مسودة" in r.text, True)
check("بلون بارز", 'w:color w:val="B00000"' in DOCXML, True)
plain = write_docx("# بلا وسم\n\nنص.\n", TMP / "p.docx", title="بلا")
check("بلا ترويسة عند الإطفاء", "مسودة" in doc.extract(plain).text, False)

print("\n── الهروب من XML ──")
esc = write_docx('# عنوان & <وسم>\n\nنص فيه "اقتباس" و& علامة.\n', TMP / "e.docx",
                 title="هروب")
try:
    with zipfile.ZipFile(esc) as z:
        ET.fromstring(z.read("word/document.xml"))
    ok = True
except ET.ParseError:
    ok = False
check("محارف XML الخاصة لا تكسر الملف", ok, True)
check("النص محفوظ", "<وسم>" in doc.extract(esc).text, True)

print("\n── الخط قابل للضبط ──")
custom = write_docx("# ع\n\nنص.\n", TMP / "f.docx", title="خط",
                    style=Style(font_cs="Simplified Arabic", size_pt=16))
with zipfile.ZipFile(custom) as z:
    d = z.read("word/document.xml").decode()
check("اسم الخط مطبَّق", 'w:cs="Simplified Arabic"' in d, True)
check("الحجم مطبَّق (نصف نقاط)", 'w:szCs w:val="32"' in d, True)

print(f"\n{'✓ كل الاختبارات ناجحة' if not FAIL else f'✗ {FAIL} اختبار فاشل'}")
print("\n\033[2mملاحظة: تحقّق البنية والقراءة العكسية فقط — لم يُفتح الملف في\n"
      "Word أو LibreOffice هنا (LibreOffice لا يعمل في بيئة البناء).\033[0m\n")
sys.exit(1 if FAIL else 0)
