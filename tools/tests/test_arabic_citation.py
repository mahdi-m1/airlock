"""اختبارات التقسيم والاستشهاد — الأساس الذي تعتمد عليه بوابة التحقق."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import arabic, citation  # noqa: E402

FAIL = 0


def check(name, got, want):
    global FAIL
    if got == want:
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}\n      المتوقع: {want!r}\n      الناتج : {got!r}")


print("\n── تطبيع النصوص ──")
check("أرقام عربية → لاتينية", arabic.normalize_digits("المادة (٩٩)"), "المادة (99)")
check("إزالة التشكيل", arabic.strip_tashkeel("العَامِل"), "العامل")
check("طي الألف والتاء المربوطة", arabic.fold("الشركة إذا"), arabic.fold("الشركه اذا"))

print("\n── تقسيم المواد ──")
TEXT = """
قانون رقم (36) لسنة 2012 بإصدار قانون العمل في القطاع الأهلي

نحن حمد بن عيسى آل خليفة ملك مملكة البحرين.

المادة (1)
في تطبيق أحكام هذا القانون يُقصد بالكلمات التالية المعاني المبينة قرينها.

المادة (2) :
لا تسري أحكام هذا القانون على موظفي الحكومة.

مادة رقم (٣)
تُحسب مدة الخدمة من تاريخ التحاق العامل بالعمل.

المادة الرابعة
يجب أن يكون عقد العمل مكتوباً باللغة العربية.

المادة (99 مكرراً) -
للعامل الحق في إجازة سنوية مدفوعة الأجر.
"""
arts = arabic.segment_articles(TEXT)
check("عدد المواد", len(arts), 5)
check("مفاتيح المواد", [a["key"] for a in arts], ["1", "2", "3", "4", "99-مكرر"])
check("رقم عربي مُطبَّع", arts[2]["number"], "3")
check("مادة بالحروف", arts[3]["number"], "4")
check("مادة مكررة", (arts[4]["number"], arts[4]["bis"]), ("99", True))
check("العنوان المصاغ", arts[4]["label"], "المادة (99 مكرر)")
check("متن المادة الأولى", arts[0]["text"].startswith("في تطبيق أحكام"), True)
check("لا تسرب من المادة التالية",
      "لا تسري" not in arts[0]["text"], True)
check("الديباجة مستبعدة", any("نحن حمد" in a["text"] for a in arts), False)

print("\n── الاستشهادات ──")
DOC = """
ولما كان الثابت أن المادة (99) من قانون العمل في القطاع الأهلي ⟦BH:law:36/2012:م99⟧
قد قررت للعامل حقًا في الإجازة، وكان مفاد المادة (١٥٦) من القانون المدني
⟦BH:dl:19/2001:م١٥٦⟧ أن الالتزام ينقضي بالوفاء، ووفقًا لقانون التحكيم ⟦BH:law:9/2015⟧.
"""
cits = citation.parse_all(DOC)
check("عدد الاستشهادات", len(cits), 3)
check("المعرّف الأول", cits[0].ref_id, "law:36/2012:99")
check("أرقام عربية في العلامة", cits[1].ref_id, "dl:19/2001:156")
check("استشهاد بلا مادة", cits[2].ref_id, "law:9/2015")
check("صياغة عربية", cits[0].to_arabic(), "المادة (99) من قانون رقم (36) لسنة 2012")
check("إعادة توليد العلامة", cits[0].to_marker(), "⟦BH:law:36/2012:م99⟧")

BAD = "المادة (5) من قانون مجهول ⟦BH:law:خمسة/2012:م5⟧ و⟦مرجع غير صالح⟧ و⟦BH:law:1/2020:م1⟧"
check("العلامات الصحيحة فقط", len(citation.parse_all(BAD)), 1)
check("رصد العلامات المشوّهة", len(citation.find_malformed(BAD)), 2)

clean = citation.render_clean("المادة (99) من قانون العمل ⟦BH:law:36/2012:م99⟧ تقرر ذلك.")
check("تنظيف الوثيقة النهائية", clean, "المادة (99) من قانون العمل تقرر ذلك.")
check("لا علامات في النص النظيف", "⟦" in clean, False)

print("\n── تشابه العناوين ──")
check("عنوان مطابق تقريبًا",
      arabic.similarity("قانون العمل في القطاع الأهلي",
                        "قانون العمل فى القطاع الاهلى") > 0.9, True)
check("عنوان مختلف",
      arabic.similarity("قانون العمل في القطاع الأهلي", "قانون التجارة") < 0.3, True)

print(f"\n{'✓ كل الاختبارات ناجحة' if not FAIL else f'✗ {FAIL} اختبار فاشل'}\n")
sys.exit(1 if FAIL else 0)
