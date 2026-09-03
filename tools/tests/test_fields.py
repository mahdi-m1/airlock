"""اختبارات تدقيق الحقول الحرجة — الطبقة التي تحصر شك القراءة الآلية."""
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from lib import fields as F  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "vf", ROOT / "tools/documents/verify_fields.py")
vf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vf)

FAIL = 0
TMP = Path(tempfile.mkdtemp())


def check(name, got, want):
    global FAIL
    if got == want:
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}\n      المتوقع: {want!r}\n      الناتج : {got!r}")


def values(text, kind):
    return sorted(f.value for f in F.find(text) if f.kind == kind)


def notes(text):
    return F.consistency(F.find(text), text)


print("\n── التواريخ ──")
check("يوم/شهر/سنة", values("حرر في 14/03/2024", "date"), ["2024-03-14"])
check("سنة-شهر-يوم", values("بتاريخ 2024-03-14", "date"), ["2024-03-14"])
check("اسم الشهر", values("الموافق 14 مارس 2024", "date"), ["2024-03-14"])
check("أرقام عربية هندية", values("في ١٤/٠٣/٢٠٢٤", "date"), ["2024-03-14"])
check("سنة من خانتين", values("في 14/03/99", "date"), ["1999-03-14"])
check("تاريخ مستحيل يُرصد",
      any("ليس تاريخًا صحيحًا" in n for n in notes("حرر في 31/02/2024")), True)
check("الهجري يُميَّز ويُنبَّه",
      any("هجري" in n for n in notes("في 12 رمضان 1445")), True)

print("\n── المبالغ ──")
# «دينارًا» و«دينار» يجب أن تتطبّعا إلى قيمة واحدة، وإلا بدت القراءتان مختلفتين
check("مبلغ بعملة", values("الأجر 620.500 دينارًا", "money"), ["620.500 دينار"])
check("والتنوين لا يصنع قيمة أخرى",
      values("الأجر 620.500 دينار", "money"), values("الأجر 620.500 دينارًا", "money"))
check("فاصلة الآلاف", values("قيمة الدعوى 12,500 دينار", "money"), ["12500 دينار"])
check("العملة قبل الرقم", values("BHD 750", "money"), ["750 bhd"])
check("خانتان عشريتان في الدينار تُنبَّه",
      any("ثلاث (فلس)" in n for n in notes("الأجر 620.50 دينارًا")), True)
check("ثلاث خانات لا تُنبَّه", notes("الأجر 620.500 دينارًا"), [])

print("\n── المدد ──")
check("لفظًا", values("مهلة ثلاثين يومًا", "duration"), ["30 يوم"])
check("مركّبًا بالواو", values("خمسة وأربعين يومًا", "duration"), ["45 يوم"])
check("مثنى", values("خلال شهرين", "duration"), ["2 شهر"])
# «إلى 01/01/2021 لمدة ثلاث سنوات» كانت تُقرأ منها مدة «2021 سنة»
check("سنة التاريخ ليست مدة",
      values("من 01/01/2020 إلى 01/01/2021 لمدة ثلاث سنوات", "duration"), ["3 سنه"])

print("\n── التماسك ──")
check("المجموع لا يساوي مفرداته",
      any("لا يتطابقان" in n for n in
          notes("الأساسي 620 دينارًا والسكن 150 دينارًا والمجموع 800 دينار")), True)
check("مجموع صحيح لا يُنبَّه",
      any("لا يتطابقان" in n for n in
          notes("الأساسي 620 دينارًا والسكن 150 دينارًا والمجموع 770 دينار")), False)
check("مدة تناقض حدّيها في السطر نفسه",
      any("لا توافق المسافة" in n for n in
          notes("يستمر العقد من 01/01/2020 إلى 01/01/2021 لمدة ثلاث سنوات")), True)
# خطاب فيه تاريخان ومدة خدمة لا علاقة بينها: تنبيه هنا يُفقد الثقة بكل تنبيه
check("تاريخان ومدة بلا صلة لا يُنبَّهان",
      any("لا توافق المسافة" in n for n in
          notes("الموافق 14 مارس 2024\nينتهي في 14/04/2024\nمدة الخدمة خمس سنوات")),
      False)
check("رقم بخانتين من كتابتين يُرصد",
      any("يخلط الأرقام" in n for n in notes("المبلغ 12٣45 دينار")), True)
check("رقم شخصي بتاريخ مستحيل",
      any("ليست تاريخًا ممكنًا" in n for n in notes("الرقم الشخصي 879912345")), True)
check("رقم شخصي بتاريخ ممكن لا يُنبَّه",
      any("ليست تاريخًا ممكنًا" in n for n in notes("الرقم الشخصي 870512345")), False)
check("نسبة فوق المائة", any("تتجاوز المائة" in n for n in notes("خصم 150%")), True)

print("\n── مقابلة القراءات ──")
one = "الأجر 620 دينارًا والمهلة ثلاثون يومًا"
two = "الأجر 620 دينارًا والمهلة سبعة وثلاثون يومًا"
check("قراءة واحدة: لا مقابلة", F.compare({"أ": one}), [])
check("قراءتان متفقتان: لا اختلاف", F.compare({"أ": one, "ب": one}), [])
diffs = F.compare({"أ": one, "ب": two})
check("اختلاف رقمي يُرصد", len(diffs) >= 2, True)
check("ويسمّي القارئين", all("أ" in d and "ب" in d for d in diffs), True)

print("\n── ورقة التدقيق ──")
items = F.find("الموافق 14 مارس 2024، الأجر 620.500 دينارًا")
sheet = TMP / "w.md"
sheet.write_text(vf.worksheet(Path("x.pdf"), items, ["ملاحظة"], ["اختلاف"],
                              "pdf", ["أ", "ب"]), encoding="utf-8")
done, blank, fixed, unread = vf.read_confirmations(sheet)
check("الورقة الفارغة لا تمر", (done, len(blank)), (0, len(items)))

filled = sheet.read_text(encoding="utf-8").split("\n")
answers = ["14 مارس 2024", "620.750 دينارا"]
i = 0
for n, line in enumerate(filled):
    if line.strip() == "- **بالأصل:**":
        filled[n] = f"- **بالأصل:** {answers[i]}"
        i += 1
sheet.write_text("\n".join(filled), encoding="utf-8")
done, blank, fixed, unread = vf.read_confirmations(sheet)
check("المملوءة تمر", (done, blank), (2, []))
check("والتصحيح يُعلَن", len(fixed), 1)
check("ويُسمّى الحقل المصحَّح", "620.750" in fixed[0], True)

filled = sheet.read_text(encoding="utf-8").replace("- **بالأصل:** 620.750 دينارا",
                                                   "- **بالأصل:** غير مقروء")
sheet.write_text(filled, encoding="utf-8")
done, blank, fixed, unread = vf.read_confirmations(sheet)
check("«غير مقروء» يُعدّ مقابلة لا تصحيحًا", (len(unread), len(fixed)), (1, 0))

print(f"\n{'✓ كل الاختبارات ناجحة' if not FAIL else f'✗ {FAIL} اختبار فاشل'}\n")
sys.exit(1 if FAIL else 0)
