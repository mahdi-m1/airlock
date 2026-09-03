"""اختبارات قوالب العقود وفاحص البنود."""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import yaml  # noqa: E402

sys.path.insert(0, str(ROOT / "tools" / "contracts"))
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("cc", ROOT / "tools/contracts/check_clauses.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

FAIL = 0
TMP = Path(tempfile.mkdtemp())
CFG = cc.load_config()
REF = ROOT / "maktab/skills/siyaghat-alaqud/references"


def check(name, got, want):
    global FAIL
    if got == want:
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}\n      المتوقع: {want!r}\n      الناتج : {got!r}")


def template_body(path: Path) -> str:
    m = re.search(r"```markdown\n(.*?)\n```", path.read_text(encoding="utf-8"), re.S)
    return m.group(1) if m else ""


print("\n── القوالب موجودة ومرتبطة ──")
for key, spec_ in CFG["types"].items():
    p = ROOT / spec_["template"]
    check(f"قالب {key} موجود", p.exists(), True)
    check(f"قالب {key} يحوي كتلة عقد", bool(template_body(p)), True)

print("\n── كل قالب يستوفي قائمته ──")
# القالب الذي لا يجتاز فاحصه يعني أن أحدهما خاطئ — والعقد الذي يُبنى عليه ناقص.
for key, spec_ in CFG["types"].items():
    body = template_body(ROOT / spec_["template"])
    f = TMP / f"{key}.md"
    f.write_text(body, encoding="utf-8")
    rep = cc.check(f, key, CFG, str(TMP / "nodb.db"))
    missing = [p["label"] for p in rep["problems"] if p["kind"] == "ناقص"]
    void = [p["label"] for p in rep["problems"] if p["kind"] == "باطل"]
    check(f"قالب {key}: لا بند إلزامي ناقص", missing, [])
    check(f"قالب {key}: لا بند باطل", void, [])

print("\n── رصد النقص ──")
naqis = TMP / "naqis.md"
naqis.write_text("# عقد عمل\nالطرف الأول والطرف الثاني.\nالأجر 800 دينار.\n",
                 encoding="utf-8")
rep = cc.check(naqis, "amal", CFG, str(TMP / "nodb.db"))
check("عقد ناقص يُرفض", rep["passed"], False)
labels = [p["label"] for p in rep["problems"]]
check("رُصد نقص الاختصاص", "القانون الواجب التطبيق والاختصاص" in labels, True)
check("رُصد نقص الإخطارات", "الإخطارات" in labels, True)
check("لكل مشكلة سبب مكتوب", all(p["why"].strip() for p in rep["problems"]), True)

print("\n── رصد الحقول غير المملوءة ──")
holes = TMP / "holes.md"
holes.write_text(template_body(REF / "qalib-aqd-amal.md"), encoding="utf-8")
rep = cc.check(holes, "amal", CFG, str(TMP / "nodb.db"))
check("القالب الخام يُرفض لحقوله", rep["passed"], False)
check("عُدّت الحقول غير المملوءة", len(rep["placeholders"]) > 5, True)
# الصائغ يحسم النوعين: يملأ <الحقل> ويختار من [اختر: أ | ب]
filled = template_body(REF / "qalib-aqd-amal.md")
filled = re.sub(r"\[اختر:([^|\]\n]{1,80})\|[^\]\n]{1,80}\]", r"\1", filled)
filled = re.sub(r"<[^<>\n]{1,80}>", "مُحدَّد", filled)
f2 = TMP / "filled.md"
f2.write_text(filled, encoding="utf-8")
rep2 = cc.check(f2, "amal", CFG, str(TMP / "nodb.db"))
check("بعد ملء الحقول وحسم البدائل: لا فراغ", rep2["placeholders"], [])
check("بعد الملء يُقبل", rep2["passed"], True)

print("\n── البنود القانونية لا تُفرض بلا سند ──")
# هذا جوهر الصدق في الأداة: قاعدة لم يُتحقق من مصدرها لا تُفرض على عقود العملاء.
batil = TMP / "batil.md"
batil.write_text(filled + "\n## بند إضافي\nيتنازل العامل عن مكافأة نهاية الخدمة.\n",
                 encoding="utf-8")
rep = cc.check(batil, "amal", CFG, str(TMP / "nodb.db"))
void_enforced = [p["label"] for p in rep["problems"] if p["kind"] == "باطل"]
void_manual = [m["label"] for m in rep["manual"] if m["kind"] == "باطل"]
check("بند التنازل رُصد", bool(void_enforced or void_manual), True)
check("لم يُفرض بلا سند", void_enforced, [])
check("أُبلغ عنه كتحقق يدوي", "تنازل العامل عن حقوق مقررة قانونًا" in void_manual, True)

print("\n── سلامة قوائم البنود ──")
seen_keys = set()
for key, spec_ in CFG["types"].items():
    for item in list(spec_.get("required", [])) + list(spec_.get("void", [])):
        check(f"{key}/{item['key']}: له basis",
              item.get("basis") in ("structural", "statutory"), True)
        if item.get("basis") == "statutory":
            check(f"{key}/{item['key']}: حقل sanad معرّف", "sanad" in item, True)
        check(f"{key}/{item['key']}: له أنماط", bool(item.get("patterns")), True)
        check(f"{key}/{item['key']}: له سبب", bool(item.get("why", "").strip()), True)
for item in CFG["common"]["required"]:
    check(f"common/{item['key']}: بنيوي", item.get("basis"), "structural")

print("\n── الواجهة ──")
r = subprocess.run([sys.executable, str(ROOT / "tools/contracts/check_clauses.py"), "--list"],
                   capture_output=True, text=True)
check("--list ينجح", r.returncode, 0)
for key in CFG["types"]:
    check(f"--list يعرض {key}", key in r.stdout, True)
r = subprocess.run([sys.executable, str(ROOT / "tools/contracts/check_clauses.py"),
                    str(naqis), "--type", "amal"], capture_output=True, text=True)
check("عقد ناقص يعيد رمز 1", r.returncode, 1)

print("\n── قالب الاستشارة ──")
p = ROOT / "maktab/skills/siyaghat-alistisharah/references/qalib-istisharah.md"
check("موجود", p.exists(), True)
body = p.read_text(encoding="utf-8")
for section in ("السؤال", "الجواب المختصر", "الوقائع المفترضة", "الأساس القانوني",
                "الخيارات المتاحة", "المخاطر والتحفظات", "التوصية"):
    check(f"يحوي «{section}»", section in body, True)


print("\n── دورة ملء الأسناد ──")
import shutil  # noqa: E402

fs_spec = importlib.util.spec_from_file_location(
    "fs", ROOT / "tools/contracts/fill_sanad.py")
fs = importlib.util.module_from_spec(fs_spec)
fs_spec.loader.exec_module(fs)

check("كل البنود القانونية لها مصطلحات بحث",
      all(i.get("search_terms") for i in fs.statutory_items(CFG)), True)
check("عدد البنود القانونية", len(fs.statutory_items(CFG)) > 0, True)

# قراءة ورقة مراجعة
sheet = TMP / "sheet.md"
sheet.write_text(
    "# ورقة\n\n## amal/ijaza\n\n**المعتمد:** `⟦BH:law:36/2012:م99⟧`\n\n---\n"
    "\n## amal/inha\n\n**المعتمد:** \n\n---\n", encoding="utf-8")
parsed = fs.parse_sheet(sheet)
check("يقرأ المعتمد", parsed.get(("amal", "ijaza")), "⟦BH:law:36/2012:م99⟧")
check("يتجاهل غير المعتمد", ("amal", "inha") in parsed, False)

# الكتابة النصية تحفظ التعليقات
original = fs.CLAUSES.read_text(encoding="utf-8")
edited, done = fs.set_sanad(original, "amal", "ijaza", "⟦BH:law:36/2012:م99⟧")
check("كُتب السند في موضعه", done, True)
check("السند ظهر", 'sanad: "⟦BH:law:36/2012:م99⟧"' in edited, True)
check("التعليقات محفوظة",
      edited.count("#") == original.count("#"), True)
check("لم يتغير غير سطر واحد",
      sum(1 for a, b in zip(original.splitlines(), edited.splitlines()) if a != b), 1)
_, missing = fs.set_sanad(original, "amal", "band_wahmi", "⟦BH:law:1/2020:م1⟧")
check("بند غير موجود لا يُكتب", missing, False)

# الملف المُسلَّم لا يحمل أسنادًا غير مُتحقق منها
check("كل الأسناد في المستودع فارغة",
      all(not (i.get("sanad") or "").strip() for i in fs.statutory_items(CFG)), True)

print(f"\n{'✓ كل الاختبارات ناجحة' if not FAIL else f'✗ {FAIL} اختبار فاشل'}\n")
sys.exit(1 if FAIL else 0)
