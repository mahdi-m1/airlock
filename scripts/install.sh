#!/usr/bin/env bash
# تثبيت المكتب — يتحقق من المتطلبات ثم يرشدك للخطوات بالترتيب.
# Guided installer. Checks prerequisites, then walks the setup in order.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_dim=$'\033[2m'; c_0=$'\033[0m'
FAIL=0
ok()   { printf '  %s✓%s %s\n' "$c_grn" "$c_0" "$1"; }
bad()  { printf '  %s✗%s %s\n' "$c_red" "$c_0" "$1"; FAIL=$((FAIL+1)); }
warn() { printf '  %s!%s %s\n' "$c_yel" "$c_0" "$1"; }

printf '\n══ تثبيت مكتب الاستشارات القانونية ══\n\n1. المتطلبات\n'

# ── نظام التشغيل و bwrap: أساس ضمان العزل ────────────────────────────
if [ "$(uname -s)" != "Linux" ]; then
  bad "النظام $(uname -s). فرض عزل الشبكة (networkScope) يعمل على Linux فقط."
  printf '    %sبدونه تصبح عزلة وكلاء القضايا وعدًا نصيًا لا قيدًا تقنيًا.%s\n' "$c_dim" "$c_0"
elif command -v bwrap >/dev/null 2>&1; then
  ok "bwrap متاح — عزل الشبكة قابل للفرض"
else
  bad "bwrap غير مثبّت. ثبّته:  sudo apt install bubblewrap"
  printf '    %sهو ما يمنع وكيل القضية تقنيًا من بلوغ أي جهة غير واجهة النموذج.%s\n' "$c_dim" "$c_0"
fi

# ── بايثون ومكتباته ──────────────────────────────────────────────────
if command -v python3 >/dev/null 2>&1; then
  PYV=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
  if python3 -c 'import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)'; then
    ok "python3 $PYV"
  else
    bad "python3 $PYV — المطلوب 3.10 أو أحدث"
  fi
  python3 -c 'import yaml' 2>/dev/null && ok "PyYAML" || {
    bad "PyYAML غير مثبّت.  pip install pyyaml"; }
  python3 -c 'import sqlite3,sys;c=sqlite3.connect(":memory:");c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")' 2>/dev/null \
    && ok "sqlite3 مع FTS5" || bad "sqlite3 بلا دعم FTS5 — البحث في المدونة لن يعمل"
else
  bad "python3 غير موجود"
fi

command -v node >/dev/null 2>&1 && ok "node $(node --version)" \
  || warn "node غير موجود — تحتاجه لتشغيل Paperclip"
# ── خلفيات معالجة المستندات ──────────────────────────────────────────
printf '\n2. معالجة المستندات\n'
ok "قراءة DOCX · ODT · RTF · HTML · نص — بالمكتبة القياسية"
ok "إصدار Word (.docx) عربي — بالمكتبة القياسية"
if command -v pdftotext >/dev/null 2>&1; then ok "قراءة PDF (poppler)"
elif python3 -c 'import pypdf' 2>/dev/null; then ok "قراءة PDF (pypdf)"
else warn "لا خلفية لقراءة PDF:  sudo apt install poppler-utils"
     printf '    %sعقود العملاء والمصادر الرسمية كثيرًا ما تكون PDF.%s\n' "$c_dim" "$c_0"; fi
if command -v tesseract >/dev/null 2>&1; then
  tesseract --list-langs 2>/dev/null | grep -q '^ara$' \
    && ok "التعرّف الضوئي مع العربية" \
    || warn "tesseract بلا الحزمة العربية:  sudo apt install tesseract-ocr-ara"
else
  warn "لا تعرّف ضوئي:  sudo apt install tesseract-ocr tesseract-ocr-ara"
  printf '    %sالمستندات الممسوحة والصور لن تُقرأ (تُرفض صراحةً ولا تُبتلع).%s\n' "$c_dim" "$c_0"
fi

# ── فحص الحزمة ───────────────────────────────────────────────────────
printf '\n3. سلامة الحزمة\n'
if python3 scripts/validate.py >/tmp/_v.txt 2>&1; then
  ok "حزمة المكتب سليمة (10 وكلاء، 11 مهارة، خط بـ10 مراحل)"
else
  bad "فشل التحقق من الحزمة:"; sed 's/^/    /' /tmp/_v.txt | tail -12
fi
for t in test_arabic_citation test_semantic test_documents test_docx; do
  if python3 "tools/tests/$t.py" >/tmp/_t.txt 2>&1; then
    ok "اختبارات $t ناجحة"
  else
    bad "فشل $t:"; sed 's/^/    /' /tmp/_t.txt | tail -8
  fi
done

# ── ملف البيئة ───────────────────────────────────────────────────────
printf '\n4. تحصين البيئة\n'
if [ -f config/env.local ]; then
  ok "config/env.local موجود"
else
  cp config/env.local.example config/env.local
  ok "أُنشئ config/env.local — ${c_yel}ضع فيه ANTHROPIC_API_KEY${c_0}"
fi

printf '\n%s%s%s\n' "$c_dim" "──────────────────────────────────────────────────────────" "$c_0"
if [ "$FAIL" -gt 0 ]; then
  printf '%s✗ %d متطلب ناقص — عالجها قبل المتابعة.%s\n\n' "$c_red" "$FAIL" "$c_0"
  exit 1
fi

cat <<'STEPS'
✓ المتطلبات مكتملة.

الخطوات التالية بالترتيب:

  1) حصّن البيئة وتحقق
       set -a; . ./config/env.local; set +a
       ./scripts/verify-isolation.sh

  2) شغّل Paperclip واستورد المكتب
       npx paperclipai onboard
       npx paperclipai company import ./maktab --dry-run     # فحص أولًا
       npx paperclipai company import ./maktab --target new \
           --new-company-name "مكتب الاستشارات القانونية" --yes

     ⚠ onboard يعيد تفعيل التليمتري في ملف الإعداد. أعد التحقق بعده:
       ./scripts/verify-isolation.sh

  3) هيّئ الخط والعزل والسقوف
       export PAPERCLIP_API_URL=http://127.0.0.1:3100
       export PAPERCLIP_API_KEY=<token>
       python3 scripts/provision.py --company-id <uuid>

  4) ابنِ المدونة القانونية — لا يعمل المكتب بدونها
       # نزّل النصوص الرسمية إلى corpus/staging/<key>.html
       python3 tools/ingest/ingest.py --from-staging
       python3 tools/corpus/corpus_cli.py stats
       python3 scripts/calibrate-threshold.py --write   # عايِر عتبة الدلالة

  5) جرّب قضية اصطناعية من طرف إلى طرف
       ./scripts/e2e-test.sh

STEPS
