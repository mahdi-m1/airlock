"""اختبارات التدقيق الدلالي — الطبقة التي تفحص أن المادة تقول ما نُسب إليها."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import semantic  # noqa: E402
from lib.quantities import conflicts, extract  # noqa: E402

FAIL = 0


def check(name, got, want):
    global FAIL
    if got == want:
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}\n      المتوقع: {want!r}\n      الناتج : {got!r}")


A99 = ("يستحق العامل إجازة سنوية بأجر أساسي لا تقل مدتها عن ثلاثين يوماً "
       "بواقع يومين ونصف عن كل شهر.")
A111 = ("يقع باطلاً كل فصل يكون تعسفياً أو مخالفاً لأحكام هذا القانون، "
        "ويستحق العامل تعويضاً عادلاً تقدره المحكمة.")
A2 = "لا تسري أحكام هذا القانون على موظفي الحكومة والأشخاص الاعتبارية العامة."

print("\n── استخراج المقادير ──")
check("رقم لاتيني", extract("خلال 30 يوما"), {(30.0, "يوم")})
check("لفظ عقد", extract("ثلاثين يوماً"), {(30.0, "يوم")})
check("مركّب بواو العطف", extract("خمسة وأربعين يوماً"), {(45.0, "يوم")})
check("مركّب بالمئات", extract("مائة وعشرين يوما"), {(120.0, "يوم")})
check("صيغة المثنى", extract("سنتين"), {(2.0, "سنه")})
check("آلاف", extract("خمسة آلاف دينار"), {(5000.0, "دينار")})
check("نسبة مئوية", extract("نسبة 50%"), {(50.0, "%")})

print("\n── تعارض المقادير ──")
check("مقدار مغلوط يُرصد",
      bool(conflicts("إجازة لا تقل عن خمسة وأربعين يوماً", A99)), True)
check("مقدار صحيح يمر",
      conflicts("إجازة لا تقل عن ثلاثين يوماً", A99), [])
check("وحدة غير واردة في المادة لا تُرصد",
      conflicts("تعويض قدره 5000 دينار", A99), [])

print("\n── الصيغ الحكمية ──")
check("الحظر يسبق الإباحة في «لا يجوز»",
      "حظر" in semantic.frames("لا يجوز لصاحب العمل ذلك"), True)
check("«لا يجوز» لا تُقرأ إباحةً",
      "إباحة" in semantic.frames("لا يجوز لصاحب العمل ذلك"), False)
check("البطلان", "بطلان" in semantic.frames(A111), True)
check("عدم السريان", "استثناء" in semantic.frames(A2), True)

print("\n── حكم الإسناد ──")
check("إسناد مطابق",
      semantic.check("كل فصل تعسفي يقع باطلاً ويستحق العامل تعويضاً عادلاً "
                     "تقدره المحكمة", A111).verdict, "مسنود")
check("مقدار مغلوط ⇒ تعارض قاطع",
      semantic.check("يستحق العامل إجازة لا تقل عن خمسة وأربعين يوماً",
                     A99).verdict, "متعارض")
check("ادعاء إباحة ومادة حظر ⇒ تعارض قاطع",
      semantic.check("يجوز لصاحب العمل إنهاء الخدمة",
                     "لا يجوز لصاحب العمل إنهاء الخدمة أثناء الإجازة").verdict,
      "متعارض")
check("نسبة حظر لمادة استحقاق ⇒ تحكيم",
      semantic.check("يحظر على صاحب العمل إنهاء الخدمة أثناء الإجازة",
                     A99).verdict, "يحتاج تحكيمًا")
check("إغفال الاستثناء ⇒ تحكيم",
      semantic.check("تسري أحكام هذا القانون على جميع العاملين", A2).verdict,
      "يحتاج تحكيمًا")
check("التعارض القاطع يحجب",
      semantic.check("إجازة لا تقل عن خمسة وأربعين يوماً", A99).blocking, True)
check("الشك لا يحجب",
      semantic.check("يحظر إنهاء الخدمة أثناء الإجازة", A99).blocking, False)

print("\n── استخراج جملة الادعاء ──")
DOC = ("# مذكرة\n\n## ثالثًا: الأسانيد\n"
       "لما كان مفاد المادة (99) ⟦BH:law:36/2012:م99⟧ أن العامل يستحق إجازة "
       "سنوية لا تقل عن ثلاثين يوماً، وكانت المادة (111) ⟦BH:law:36/2012:م111⟧ "
       "تقضي ببطلان الفصل التعسفي، فإن الدعوى تقوم.\n")
m1, m2 = DOC.find("⟦"), DOC.find("⟦", DOC.find("⟦") + 1)
L = len("⟦BH:law:36/2012:م99⟧")
spans = [(m1, L), (m2, len("⟦BH:law:36/2012:م111⟧"))]
c1 = semantic.claim_span(DOC, m1, L, spans)
c2 = semantic.claim_span(DOC, m2, len("⟦BH:law:36/2012:م111⟧"), spans)

check("لا يبتلع سطر العنوان", "الأسانيد" in c1, False)
check("لا ينقطع عند التفاف السطر", "ثلاثين" in c1, True)
check("لا يبتلع ادعاء العلامة المجاورة", "بطلان" in c1, False)
check("الادعاء الثاني يخص مادته", "بطلان" in c2 and "ثلاثين" not in c2, True)
check("العلامات تُزال من الادعاء", "⟦" in c1 or "⟦" in c2, False)


print("\n── معايرة العتبة ──")
import math, random  # noqa: E402
from lib.calibrate import MIN_ARTICLES, calibrate  # noqa: E402
from lib.arabic import fold, stem  # noqa: E402


def _synthetic_corpus(n=250, seed=7):
    """مدونة اصطناعية لاختبار حساب المعايرة وحده — لا محتوى قانوني."""
    rng = random.Random(seed)
    topics = [
        "الأجر الأساسي العلاوة البدل الحد الأدنى الاستقطاع الدفع الشهري",
        "الإجازة السنوية المرضية الوضع الرصيد التأجيل البدل النقدي",
        "الفصل الإنهاء الإخطار المهلة التعسفي التعويض الاستقالة الخدمة",
        "السلامة المهنية الوقاية الإصابة المخاطر التدريب المعدات الحماية",
        "الشركة الحصص الشريك المدير الجمعية العمومية التصفية",
        "العقد الالتزام الفسخ التنفيذ العيني الشرط الجزائي المدين الدائن",
        "البينة الشهادة المحرر الرسمي العرفي القرينة اليمين الخبرة",
        "التقادم المدة الانقطاع الوقف السقوط الميعاد الطعن الاستئناف",
    ]
    generic = "يجب على وفق أحكام هذا القانون في حالة أن يكون الطرف خلال المدة".split()
    rows = []
    for i in range(n):
        w = topics[i % len(topics)].split()
        body = rng.sample(w, k=min(len(w), rng.randint(6, 9))) + rng.sample(generic, k=6)
        rng.shuffle(body)
        rows.append((f"law:{i // 32 + 1}/2020", " ".join(body)))
    df = {}
    for _, t in rows:
        for tok in {stem(x) for x in fold(t).split() if len(x) > 2}:
            df[tok] = df.get(tok, 0) + 1
    idf = {t: math.log((len(rows) + 1) / (c + 0.5)) for t, c in df.items()}
    return rows, idf


rows, idf = _synthetic_corpus()
big = calibrate(rows, idf)
check("مدونة بحجم حقيقي ⇒ موثوقة", big.reliable, True)
check("العتبة ترتفع فوق الافتراضية", big.threshold > 0.35, True)
check("الفوات ضمن المستهدف", big.miss_rate <= 0.06, True)
check("لا NaN في المخرج (JSON صالحة)", "NaN" in big.to_json(), False)
check("العتبة لا تتجاوز السقف", big.threshold <= 0.75, True)

small = calibrate(rows[:10], idf)
check("مدونة صغيرة ⇒ غير موثوقة", small.reliable, False)
check("مدونة صغيرة ⇒ لا معدلات مضللة", small.miss_rate, None)

check("المعايرة قابلة لإعادة الإنتاج",
      calibrate(rows, idf).threshold, big.threshold)
check("حد الموثوقية معلن", MIN_ARTICLES >= 100, True)

print(f"\n{'✓ كل الاختبارات ناجحة' if not FAIL else f'✗ {FAIL} اختبار فاشل'}\n")
sys.exit(1 if FAIL else 0)
