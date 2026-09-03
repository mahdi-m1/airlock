#!/usr/bin/env bash
# اختبار شامل للنواة الحتمية للمكتب: استيراد ← بحث ← صياغة ← بوابة ← تسليم.
#
# End-to-end test of the deterministic core. Runs entirely offline against a
# fixture corpus in a temp dir — it never touches the real corpus and needs
# neither Paperclip nor a model. What it proves is exactly the part that must
# not be taken on trust: that a fabricated citation is actually stopped.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_dim=$'\033[2m'; c_0=$'\033[0m'
PASS=0; FAIL=0
step() { printf '\n%s── %s%s\n' "$c_dim" "$1" "$c_0"; }
ok()   { printf '  %s✓%s %s\n' "$c_grn" "$c_0" "$1"; PASS=$((PASS+1)); }
bad()  { printf '  %s✗%s %s\n' "$c_red" "$c_0" "$1"; FAIL=$((FAIL+1)); }

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
DB="$TMP/corpus.db"

printf '\n══ اختبار شامل للمكتب ══\n'

# ── 0. الأدوات ────────────────────────────────────────────────────────
step "0. وحدات المعالجة العربية والإسناد"
if python3 tools/tests/test_arabic_citation.py >"$TMP/unit.log" 2>&1; then
  ok "اختبارات التقسيم والإسناد ناجحة"
else
  bad "فشل اختبار التقسيم والإسناد"; tail -12 "$TMP/unit.log" | sed 's/^/      /'
fi
if python3 tools/tests/test_semantic.py >"$TMP/sem.log" 2>&1; then
  ok "اختبارات التدقيق الدلالي ناجحة"
else
  bad "فشل اختبار التدقيق الدلالي"; tail -14 "$TMP/sem.log" | sed 's/^/      /'
fi
if python3 tools/tests/test_documents.py >"$TMP/doc.log" 2>&1; then
  ok "اختبارات معالجة المستندات ناجحة (أمان + دقة)"
else
  bad "فشل اختبار المستندات"; tail -14 "$TMP/doc.log" | sed 's/^/      /'
fi
if python3 tools/tests/test_docx.py >"$TMP/docx.log" 2>&1; then
  ok "اختبارات إصدار Word ناجحة (بنية + اتجاه عربي)"
else
  bad "فشل اختبار إصدار Word"; tail -14 "$TMP/docx.log" | sed 's/^/      /'
fi
if python3 tools/tests/test_contracts.py >"$TMP/con.log" 2>&1; then
  ok "اختبارات قوالب العقود وفاحص البنود ناجحة"
else
  bad "فشل اختبار العقود"; tail -14 "$TMP/con.log" | sed 's/^/      /'
fi
if python3 tools/tests/test_sources.py >"$TMP/src.log" 2>&1; then
  ok "اختبارات سجل المصادر وتسجيل الروابط ناجحة"
else
  bad "فشل اختبار سجل المصادر"; tail -14 "$TMP/src.log" | sed 's/^/      /'
fi

# ── 1. سلامة الحزمة ───────────────────────────────────────────────────
step "1. سلامة حزمة المكتب"
if python3 scripts/validate.py >"$TMP/val.log" 2>&1; then
  ok "الحزمة سليمة والخط متسق"
else
  bad "فشل التحقق"; tail -12 "$TMP/val.log" | sed 's/^/      /'
fi

# ── 2. الاستيراد ──────────────────────────────────────────────────────
step "2. استيراد المدونة من مصدر رسمي (نموذج اختباري)"
python3 - "$TMP" <<'PY' >/dev/null
import sys, yaml, pathlib
tmp = pathlib.Path(sys.argv[1])
src = yaml.safe_load(open('corpus/sources.yaml', encoding='utf-8'))
src['ingest'].update(staging_dir='tools/tests/fixtures/staging',
                     index_db=str(tmp/'corpus.db'),
                     records_jsonl=str(tmp/'records.jsonl'))
# توثيق اختباري للنموذج: التوثيق شرط في الاستشهاد، فبدونه لا يمر أي فحص
# لاحق. هذه قيم اختبارية لا مرجع لها — النموذج نفسه ليس نصًا قانونيًا.
for inst in src['instruments']:
    if inst['key'] == 'labour-private-sector':
        inst.update(url='https://lloc.gov.bh/fixture',
                    gazette_issue='0000', gazette_date='2012-07-26')
(tmp/'sources.yaml').write_text(yaml.safe_dump(src, allow_unicode=True), encoding='utf-8')
PY
if python3 tools/ingest/ingest.py --sources "$TMP/sources.yaml" \
     --only labour-private-sector >"$TMP/ingest.log" 2>&1; then
  N=$(python3 tools/corpus/corpus_cli.py --db "$DB" stats | grep -oE '[0-9]+ مادة' | head -1)
  ok "استُورد التشريع وتحقق عنوانه — $N"
else
  bad "فشل الاستيراد"; tail -8 "$TMP/ingest.log" | sed 's/^/      /'
fi

cat > "$TMP/good.md" <<'MD'
# مذكرة قانونية

## أولًا: الوقائع
عمل المدعي لدى المدعى عليها من 2019 حتى إنهاء خدمته في 2024 بكتاب لم يتضمن سببًا.

## ثالثًا: الأسانيد القانونية
لما كان مفاد المادة (111) من قانون العمل في القطاع الأهلي ⟦BH:law:36/2012:م111⟧
أن كل فصل تعسفي يقع باطلًا ويستحق العامل عنه تعويضًا عادلًا تقدره المحكمة، وكانت
المادة (99) من ذات القانون ⟦BH:law:36/2012:م99⟧ تقرر للعامل إجازة سنوية بأجر
أساسي، فإن المدعي يستحق التعويض وبدل الإجازات معًا.

## سادسًا: التوصية
رفع الدعوى أمام المحكمة العمالية.
MD

# ── 2ب. التوثيق شرط في الاستشهاد ─────────────────────────────────────
step "2ب. نص بلا توثيق جريدة لا يُستشهد به"
python3 - "$TMP" <<'PYX' >/dev/null
import sys, yaml, pathlib
tmp = pathlib.Path(sys.argv[1])
src = yaml.safe_load(open('corpus/sources.yaml', encoding='utf-8'))
src['ingest'].update(staging_dir='tools/tests/fixtures/staging',
                     index_db=str(tmp/'noprov.db'), records_jsonl=str(tmp/'np.jsonl'))
(tmp/'noprov.yaml').write_text(yaml.safe_dump(src, allow_unicode=True), encoding='utf-8')
PYX
python3 tools/ingest/ingest.py --sources "$TMP/noprov.yaml" \
  --only labour-private-sector >"$TMP/np.log" 2>&1
if grep -q "ينقص التوثيق" "$TMP/np.log"; then
  ok "رُصد نقص توثيق الجريدة الرسمية"
else
  bad "لم يُرصد نقص التوثيق"
fi
# لا تُستعمل أنبوبة هنا: pipefail يجعل حالة الأنبوبة ترث رمز البوابة (1 عند
# الرفض) فيبدو الفحص فاشلًا وهو ناجح.
python3 tools/citation-gate/gate.py "$TMP/good.md" --kind memo \
  --db "$TMP/noprov.db" >"$TMP/np-gate.log" 2>&1
if grep -q "غير مُتحقق منه" "$TMP/np-gate.log"; then
  ok "الإسناد إلى نص غير موثّق يُرفض"
else
  bad "مرّ إسناد إلى نص غير موثّق"; tail -5 "$TMP/np-gate.log" | sed 's/^/      /'
fi

# ── 3. البحث المقتطع ──────────────────────────────────────────────────
step "3. البحث المقتطع يجد المادة الحاكمة"
if python3 tools/corpus/corpus_cli.py --db "$DB" search "الفصل التعسفي تعويض" \
     --area labour --limit 3 2>/dev/null | grep -q 'BH:law:36/2012:م111'; then
  ok "«الفصل التعسفي» ← المادة (111) رغم اختلاف التصريف"
else
  bad "البحث لم يجد المادة الحاكمة"
fi
if python3 tools/corpus/corpus_cli.py --db "$DB" search "براءة الاختراع" \
     --area labour >/dev/null 2>&1; then
  bad "البحث أعاد نتائج لموضوع خارج المدونة"
else
  ok "موضوع خارج المدونة يعيد لا شيء بدل تخمين"
fi

# ── 4. البوابة تقبل المسودة الصحيحة ──────────────────────────────────
step "4. مسودة بإسناد صحيح"
if python3 tools/citation-gate/gate.py "$TMP/good.md" --kind memo --db "$DB" \
     --render "$TMP/final.md" >"$TMP/g1.log" 2>&1; then
  ok "قُبلت المسودة — كل إسناد يُحل"
else
  bad "رُفضت مسودة صحيحة"; sed 's/^/      /' "$TMP/g1.log"
fi

# ── 5. البوابة ترفض الإسناد الملفّق — الفحص الحاسم ───────────────────
step "5. مسودة بإسناد ملفّق (يجب أن تُرفض)"
cat > "$TMP/bad.md" <<'MD'
# مذكرة قانونية

## ثالثًا: الأسانيد القانونية
تنص المادة (777) من قانون العمل ⟦BH:law:36/2012:م777⟧ على بطلان الفصل،
ويؤيده نص المادة (5) من قانون الشركات ⟦BH:dl:21/2001:م5⟧، وكذلك ⟦مرجع⟧.
MD
python3 tools/citation-gate/gate.py "$TMP/bad.md" --kind memo --db "$DB" \
  >"$TMP/g2.log" 2>&1
if [ $? -ne 0 ]; then
  ok "رُفضت المسودة الملفّقة"
  grep -q "غير موجودة في" "$TMP/g2.log" && ok "  رُصدت مادة لا وجود لها" \
    || bad "  لم تُرصد المادة غير الموجودة"
  grep -q "غير موجود في المدونة" "$TMP/g2.log" && ok "  رُصد تشريع غير مستورد" \
    || bad "  لم يُرصد التشريع غير المستورد"
  grep -q "مشوّهة" "$TMP/g2.log" && ok "  رُصدت علامة مشوّهة" \
    || bad "  لم تُرصد العلامة المشوّهة"
else
  bad "مرّت مسودة ملفّقة — هذا عطب جسيم"
fi

# ── 6. قسم قانوني بلا سند ────────────────────────────────────────────
step "6. قسم قانوني بلا أي إسناد (يجب أن يُرفض)"
cat > "$TMP/nocite.md" <<'MD'
# مذكرة قانونية

## ثالثًا: الأسانيد القانونية
من المستقر عليه فقهًا وقضاءً أن الفصل دون مبرر يوجب التعويض، وهو ما ينطبق هنا.
MD
if python3 tools/citation-gate/gate.py "$TMP/nocite.md" --kind memo --db "$DB" \
     >"$TMP/g3.log" 2>&1; then
  bad "قُبل قسم قانوني بلا سند"
else
  grep -q "بلا أي إسناد" "$TMP/g3.log" && ok "رُفض القسم القانوني غير المسند" \
    || bad "رُفضت المسودة لكن ليس للسبب الصحيح"
fi

# ── 6ب. التدقيق الدلالي: مقدار مغلوط ─────────────────────────────────
step "6ب. مقدار مغلوط منسوب لمادة صحيحة (يجب أن يُرفض)"
cat > "$TMP/figure.md" <<'MD'
# مذكرة قانونية

## ثالثًا: الأسانيد القانونية
لما كان مفاد المادة (99) من قانون العمل ⟦BH:law:36/2012:م99⟧ أن العامل يستحق
إجازة سنوية لا تقل مدتها عن خمسة وأربعين يوماً، وكانت المادة (111)
⟦BH:law:36/2012:م111⟧ تقضي ببطلان الفصل التعسفي واستحقاق تعويض عادل تقدره
المحكمة، فإن المدعي يستحق الأمرين.
MD
python3 tools/citation-gate/gate.py "$TMP/figure.md" --kind memo --db "$DB" \
  >"$TMP/g4.log" 2>&1
if [ $? -eq 1 ] && grep -q "غير وارد في المادة" "$TMP/g4.log"; then
  ok "رُصد مقدار منسوب لمادة لا تحمله — المادة موجودة والرقم صحيح"
else
  bad "مرّ مقدار مغلوط"; sed 's/^/      /' "$TMP/g4.log" | head -8
fi

# ── 6ج. التدقيق الدلالي: حكم لا تحمله المادة ─────────────────────────
step "6ج. حكم منسوب لمادة لا تحمله (يجب أن يُحال للتحكيم)"
cat > "$TMP/attrib.md" <<'MD'
# مذكرة قانونية

## ثالثًا: الأسانيد القانونية
لما كان مفاد المادة (99) من قانون العمل ⟦BH:law:36/2012:م99⟧ أنه يحظر على صاحب
العمل إنهاء خدمة العامل أثناء إجازته السنوية، وكانت المادة (111)
⟦BH:law:36/2012:م111⟧ تقضي ببطلان الفصل التعسفي واستحقاق تعويض عادل تقدره
المحكمة، فإن الفصل باطل.
MD
python3 tools/citation-gate/gate.py "$TMP/attrib.md" --kind memo --db "$DB" \
  --worksheet "$TMP/tahkim.md" --render "$TMP/nope.md" >"$TMP/g5.log" 2>&1
RC=$?
if [ "$RC" -eq 3 ]; then
  ok "أُحيل للتحكيم الدلالي (رمز 3) بدل القبول الصامت"
else
  bad "رمز الخروج $RC بدل 3"; sed 's/^/      /' "$TMP/g5.log" | head -8
fi
[ -f "$TMP/tahkim.md" ] && ok "  أُنتجت ورقة التحكيم" || bad "  لم تُنتج ورقة التحكيم"
grep -q "الحكم:" "$TMP/tahkim.md" 2>/dev/null \
  && ok "  الورقة تطلب حكمًا صريحًا لكل بند" || bad "  الورقة بلا حقل حكم"
grep -q "نص المادة كما في المدونة" "$TMP/tahkim.md" 2>/dev/null \
  && ok "  الورقة تعرض نص المادة للمقارنة" || bad "  الورقة بلا نص المادة"
[ -f "$TMP/nope.md" ] \
  && bad "  أُنتجت وثيقة نهائية رغم تحكيم معلّق" \
  || ok "  لا وثيقة نهائية قبل حسم التحكيم"

# ── 6د. معايرة العتبة ────────────────────────────────────────────────
step "6د. معايرة عتبة الدلالة ترفض مدونة أصغر من أن تُعاير"
python3 scripts/calibrate-threshold.py --db "$DB" --out "$TMP/calib.json" --write \
  >"$TMP/cal.log" 2>&1
if [ $? -ne 0 ] && [ ! -f "$TMP/calib.json" ]; then
  ok "رُفضت الكتابة — عتبة من مدونة ناقصة قد تُضعف الفحص"
else
  bad "كُتبت عتبة من مدونة أصغر من أن تُعاير"
fi
if python3 tools/citation-gate/gate.py "$TMP/good.md" --kind memo --db "$DB" 2>/dev/null \
     | grep -q "لم تُعاير بعد"; then
  ok "البوابة تعلن سقوطها للعتبة الافتراضية بدل ادعاء معايرة"
else
  bad "البوابة لا تعلن مصدر العتبة"
fi

# ── 6هـ. الإصدار بصيغة Word ──────────────────────────────────────────
step "6هـ. الإصدار بصيغة Word لا يتخطى البوابة"
python3 tools/documents/export_cli.py "$TMP/bad.md" --kind memo --db "$DB" \
  --out "$TMP/marfud.docx" >"$TMP/x1.log" 2>&1
if [ $? -ne 0 ] && [ ! -f "$TMP/marfud.docx" ]; then
  ok "مسودة مردودة لا يُنتج لها ملف Word"
else
  bad "صُدّرت مسودة مردودة — عطب جسيم"
fi
python3 tools/documents/export_cli.py "$TMP/good.md" --kind memo --db "$DB" \
  --out "$TMP/mudhakkira.docx" >"$TMP/x2.log" 2>&1
if [ $? -eq 0 ] && [ -f "$TMP/mudhakkira.docx" ]; then
  ok "المسودة المُجازة تصدر بصيغة Word"
  if python3 -c 'import sys,zipfile;d=zipfile.ZipFile(sys.argv[1]).read("word/document.xml").decode();assert "<w:bidi/>" in d and "<w:rtl/>" in d and "w:szCs" in d;assert "\u27e6" not in d;assert "\u0645\u0633\u0648\u062f\u0629" in d' "$TMP/mudhakkira.docx" 2>/dev/null; then
    ok "  عربية باتجاه صحيح، بلا علامات آلية، بترويسة المسودة"
  else
    bad "  الوثيقة الصادرة معطوبة"
  fi
else
  bad "تعذّر إصدار مسودة مُجازة"; sed 's/^/      /' "$TMP/x2.log" | tail -6
fi

# ── 6و. فاحص بنود العقود ─────────────────────────────────────────────
step "6و. فاحص بنود العقود"
printf '# %s\n%s\n' "عقد عمل" "بين الطرف الأول والطرف الثاني. الأجر 800 دينار." \
  > "$TMP/aqd-naqis.md"
python3 tools/contracts/check_clauses.py "$TMP/aqd-naqis.md" --type amal \
  >"$TMP/c1.log" 2>&1
if [ $? -eq 1 ] && grep -q "بند إلزامي ناقص" "$TMP/c1.log"; then
  ok "عقد ناقص البنود يُرفض"
else
  bad "مرّ عقد ناقص"
fi
if grep -q "تحقق يدوي" "$TMP/c1.log"; then
  ok "البنود القانونية بلا سند تُبلَّغ ولا تُفرض"
else
  bad "بند قانوني فُرض بلا سند"
fi

# ── 7. الوثيقة النهائية ───────────────────────────────────────────────
step "7. الوثيقة النهائية نظيفة من العلامات الآلية"
if [ -f "$TMP/final.md" ]; then
  if grep -q '⟦' "$TMP/final.md"; then
    bad "بقيت علامات آلية في الوثيقة النهائية"
  else
    ok "لا علامات آلية"
  fi
  grep -q "المادة (111)" "$TMP/final.md" \
    && ok "الإشارة القانونية العربية محفوظة" \
    || bad "فُقدت الإشارة القانونية عند التنظيف"
  grep -qE ' $' "$TMP/final.md" && bad "مسافات زائدة آخر الأسطر" \
    || ok "التنسيق سليم"
else
  bad "لم تُنتج الوثيقة النهائية"
fi

# ── الخلاصة ───────────────────────────────────────────────────────────
printf '\n%s%s%s\n' "$c_dim" "──────────────────────────────────────────────────────────" "$c_0"
if [ "$FAIL" -eq 0 ]; then
  printf '%s✓ نجح الاختبار الشامل — %d فحصًا.%s\n' "$c_grn" "$PASS" "$c_0"
  printf '  النواة الحتمية تعمل: لا يخرج من المكتب إسناد لا يُحل.\n\n'
  exit 0
fi
printf '%s✗ فشل %d من %d فحصًا.%s\n\n' "$c_red" "$FAIL" "$((PASS+FAIL))" "$c_0"
exit 1
