#!/usr/bin/env bash
# تثبيت مكتب الاستشارات القانونية — سكربت واحد: يفحص، ويثبّت، ويختبر.
#
# scripts/install.sh يفحص ويرشد. هذا ينفّذ.
#
#   ./scripts/setup.sh                 # يعرض الخطة، يسأل، ثم ينفّذ ويختبر
#   ./scripts/setup.sh --dry-run       # اعرض ما سيُنفَّذ ولا تنفّذ شيئًا
#   ./scripts/setup.sh --yes           # بلا أسئلة (للأتمتة)
#   ./scripts/setup.sh --mode a        # متطلبات الأدوات وحدها (بلا Paperclip)
#   ./scripts/setup.sh --no-sudo       # لا تلمس حزم النظام
#   ./scripts/setup.sh --tests-only    # الاختبارات فقط
#
# لا يُثبَّت شيء قبل أن ترى قائمة الأوامر بالضبط وتوافق عليها. وكل ما يُثبَّت
# يُعاد فحصه بعده: التقرير النهائي من فحص فعلي لا من نجاح أمر التثبيت.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_blu=$'\033[1m'
c_dim=$'\033[2m'; c_0=$'\033[0m'
ok()   { printf '  %s✓%s %s\n' "$c_grn" "$c_0" "$1"; }
bad()  { printf '  %s✗%s %s\n' "$c_red" "$c_0" "$1"; }
warn() { printf '  %s!%s %s\n' "$c_yel" "$c_0" "$1"; }
dim()  { printf '    %s%s%s\n' "$c_dim" "$1" "$c_0"; }
head_() { printf '\n%s%s%s\n' "$c_blu" "$1" "$c_0"; }

MODE=b; ASSUME_YES=0; DRY=0; USE_SUDO=1; TESTS_ONLY=0; SKIP_TESTS=0; WITH_NODE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y)     ASSUME_YES=1 ;;
    --dry-run|-n) DRY=1 ;;
    --no-sudo)    USE_SUDO=0 ;;
    --tests-only) TESTS_ONLY=1 ;;
    --skip-tests) SKIP_TESTS=1 ;;
    --with-node)  WITH_NODE=1 ;;
    --mode)       shift; MODE="${1:-b}" ;;
    --mode=*)     MODE="${1#*=}" ;;
    -h|--help)    sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf '%sخيار غير معروف: %s%s\n' "$c_red" "$1" "$c_0"; exit 2 ;;
  esac
  shift
done
[ "$MODE" = a ] || [ "$MODE" = b ] || { echo "--mode يقبل a أو b"; exit 2; }

# ── كشف البيئة ────────────────────────────────────────────────────────
PM=""; PM_INSTALL=""; PM_REFRESH=""
if   command -v apt-get >/dev/null 2>&1; then PM=apt;    PM_INSTALL="apt-get install -y"; PM_REFRESH="apt-get update"
elif command -v dnf     >/dev/null 2>&1; then PM=dnf;    PM_INSTALL="dnf install -y"
elif command -v pacman  >/dev/null 2>&1; then PM=pacman; PM_INSTALL="pacman -S --noconfirm"
elif command -v zypper  >/dev/null 2>&1; then PM=zypper; PM_INSTALL="zypper install -y"
elif command -v apk     >/dev/null 2>&1; then PM=apk;    PM_INSTALL="apk add"
fi
SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"
[ "$USE_SUDO" -eq 1 ] || { PM=""; }
[ -z "$SUDO" ] || command -v sudo >/dev/null 2>&1 || { PM=""; }

# اسم الحزمة يختلف بين المديرين — بلا خريطة يفشل التثبيت على نصف الأنظمة
pkg_for() {
  case "$1:$PM" in
    bwrap:apt)     echo bubblewrap ;;   bwrap:dnf)     echo bubblewrap ;;
    bwrap:pacman)  echo bubblewrap ;;   bwrap:zypper)  echo bubblewrap ;;
    bwrap:apk)     echo bubblewrap ;;
    pdftotext:apt) echo poppler-utils ;; pdftotext:dnf) echo poppler-utils ;;
    pdftotext:pacman) echo poppler ;;    pdftotext:zypper) echo poppler-tools ;;
    pdftotext:apk) echo poppler-utils ;;
    tesseract:apt) echo "tesseract-ocr tesseract-ocr-ara" ;;
    tesseract:dnf) echo "tesseract tesseract-langpack-ara" ;;
    tesseract:pacman) echo "tesseract tesseract-data-ara" ;;
    tesseract:zypper) echo "tesseract-ocr tesseract-ocr-traineddata-arabic" ;;
    tesseract:apk) echo "tesseract-ocr tesseract-ocr-data-ara" ;;
    yaml:apt)      echo python3-yaml ;;  yaml:dnf)     echo python3-pyyaml ;;
    yaml:pacman)   echo python-yaml ;;   yaml:zypper)  echo python3-PyYAML ;;
    yaml:apk)      echo py3-yaml ;;
    *) echo "" ;;
  esac
}

# ── الفحوص ────────────────────────────────────────────────────────────
have_python() { command -v python3 >/dev/null 2>&1 &&
  python3 -c 'import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; }
have_yaml()   { python3 -c 'import yaml' 2>/dev/null; }
have_fts5()   { python3 -c 'import sqlite3;sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")' 2>/dev/null; }
have_bwrap()  { command -v bwrap >/dev/null 2>&1; }
have_pdf()    { command -v pdftotext >/dev/null 2>&1; }
have_ocr_ara(){ command -v tesseract >/dev/null 2>&1 &&
  tesseract --list-langs 2>/dev/null | grep -q '^ara$'; }
have_node()   { command -v node >/dev/null 2>&1 &&
  [ "$(printf '%s\n24.11.0\n' "$(node --version | tr -d v)" | sort -V | head -1)" = 24.11.0 ]; }
is_linux()    { [ "$(uname -s)" = Linux ]; }

# ── بناء الخطة ────────────────────────────────────────────────────────
declare -a PLAN_CMDS=() PLAN_WHY=() MANUAL=()
add() { PLAN_CMDS+=("$1"); PLAN_WHY+=("$2"); }
sys_add() {   # الأداة، السبب
  local pkg; pkg="$(pkg_for "$1")"
  if [ -z "$PM" ] || [ -z "$pkg" ]; then
    MANUAL+=("$1 — $2"); return
  fi
  add "$SUDO $PM_INSTALL $pkg" "$2"
}

head_ "══ تثبيت مكتب الاستشارات القانونية ══"
printf '%sالوضع (%s): %s%s\n' "$c_dim" "$([ "$MODE" = a ] && echo 'أ' || echo 'ب')" \
  "$([ "$MODE" = a ] && echo 'الأدوات وحدها — بايثون فقط' || echo 'المكتب الكامل — يضيف Paperclip والعزل')" "$c_0"
printf '%sمدير الحزم: %s   الصلاحية: %s%s\n\n' "$c_dim" "${PM:-غير متاح}" \
  "$([ -n "$SUDO" ] && echo 'sudo' || echo 'root')" "$c_0"

head_ "١· الفحص"
have_python && ok "python3 $(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')" \
            || { bad "python3 ≥ 3.10 غير متاح"; MANUAL+=("python3 ≥ 3.10 — لا يعمل شيء بدونه"); }
have_yaml  && ok "PyYAML" || { bad "PyYAML"; sys_add yaml "قراءة سجل المصادر وإعدادات المكتب"; }
have_fts5  && ok "sqlite3 مع FTS5" \
           || { bad "sqlite3 بلا FTS5"; MANUAL+=("sqlite3/FTS5 — أعد بناء بايثون بدعم FTS5"); }
have_pdf   && ok "قراءة PDF (poppler)" \
           || { warn "قراءة PDF"; sys_add pdftotext "أكثر المصادر الرسمية وعقود العملاء PDF"; }
have_ocr_ara && ok "التعرّف الضوئي مع العربية" \
             || { warn "التعرّف الضوئي العربي"; sys_add tesseract "المستندات الممسوحة والصور"; }

if [ "$MODE" = b ]; then
  is_linux || { bad "النظام $(uname -s) — فرض عزل الشبكة يعمل على Linux فقط"
                MANUAL+=("Linux — العزل على غيره وعدٌ نصي لا قيد تقني"); }
  have_bwrap && ok "bwrap — عزل الشبكة قابل للفرض" \
             || { bad "bwrap"; sys_add bwrap "به يُمنع وكيل القضية من بلوغ أي جهة غير واجهة النموذج"; }
  if have_node; then ok "node $(node --version)"
  elif [ "$WITH_NODE" -eq 1 ]; then
    bad "node ≥ 24.11"
    add 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] || curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash; . "$NVM_DIR/nvm.sh"; nvm install 24' \
        "Paperclip يشترط Node 24.11 فأحدث"
  else
    bad "node ≥ 24.11 — الحالي: $(command -v node >/dev/null 2>&1 && node --version || echo 'غير مثبّت')"
    MANUAL+=("node ≥ 24.11 — أعد التشغيل بـ--with-node لتثبيته عبر nvm، أو ثبّته بنفسك")
  fi
fi

# ── العرض والموافقة ───────────────────────────────────────────────────
if [ "$TESTS_ONLY" -eq 0 ] && [ ${#PLAN_CMDS[@]} -gt 0 ]; then
  head_ "٢· ما سيُنفَّذ"
  [ -n "$PM_REFRESH" ] && printf '  %s$ %s %s%s\n' "$c_dim" "$SUDO" "$PM_REFRESH" "$c_0"
  for i in "${!PLAN_CMDS[@]}"; do
    printf '  $ %s\n' "${PLAN_CMDS[$i]}"
    dim "${PLAN_WHY[$i]}"
  done
  if [ "$DRY" -eq 1 ]; then
    printf '\n%s— عرض فقط (--dry-run). لم يُنفَّذ شيء.%s\n\n' "$c_dim" "$c_0"
  elif [ "$ASSUME_YES" -eq 0 ]; then
    printf '\n  تنفيذ؟ [y/N] '
    read -r reply </dev/tty 2>/dev/null || reply=n
    case "$reply" in [yY]*) ;; *) printf '%s  أُلغي. الاختبارات ستُشغَّل على ما هو مثبّت.%s\n' "$c_dim" "$c_0"; DRY=1 ;; esac
  fi
  if [ "$DRY" -eq 0 ]; then
    head_ "٣· التنفيذ"
    if [ -n "$PM_REFRESH" ]; then
      printf '  %s$ %s %s%s\n' "$c_dim" "$SUDO" "$PM_REFRESH" "$c_0"
      $SUDO $PM_REFRESH >/tmp/_setup_pm.log 2>&1 || warn "تعذّر تحديث فهرس الحزم — يتابع"
    fi
    for i in "${!PLAN_CMDS[@]}"; do
      printf '  $ %s\n' "${PLAN_CMDS[$i]}"
      if bash -c "${PLAN_CMDS[$i]}" >/tmp/_setup_step.log 2>&1; then ok "تمّ"
      else bad "فشل — آخر السطور:"; tail -6 /tmp/_setup_step.log | sed 's/^/      /'; fi
    done
    # PyYAML: إن لم تنفع حزمة النظام فالمسار الثاني pip، ومنه --break-system-packages
    if ! have_yaml; then
      for c in "python3 -m pip install --quiet pyyaml" \
               "python3 -m pip install --quiet --break-system-packages pyyaml"; do
        printf '  $ %s\n' "$c"
        bash -c "$c" >/tmp/_setup_step.log 2>&1 && have_yaml && { ok "تمّ"; break; } \
          || bad "فشل"
      done
    fi
  fi
fi

# ── ملف البيئة ────────────────────────────────────────────────────────
if [ "$TESTS_ONLY" -eq 0 ] && [ "$DRY" -eq 0 ]; then
  head_ "٤· ملف البيئة"
  if [ -f config/env.local ]; then ok "config/env.local موجود — لم يُمس"
  else cp config/env.local.example config/env.local && ok "أُنشئ config/env.local"; fi
  if grep -qE '^ANTHROPIC_API_KEY=.+' config/env.local 2>/dev/null; then
    ok "ANTHROPIC_API_KEY مضبوط"
  else
    warn "ANTHROPIC_API_KEY فارغ — يلزم للوضع (ب) وحده"
    dim "ضعه في config/env.local (الملف في .gitignore ولا يُرفع)"
  fi
fi

# ── إعادة الفحص ───────────────────────────────────────────────────────
head_ "٥· التحقق بعد التثبيت"
FAIL_A=0; FAIL_B=0
FAIL_O=0
# ثلاث درجات لا درجتان: لازم للأدوات، لازم للمنصة، واختياري يوسّع ما تقرؤه.
# خلط الاختياري باللازم كان سيوقف من لا يحتاج قراءة PDF أصلًا.
chk() {  # الوصف، الأمر، الدرجة (a|b|o)
  if eval "$2"; then ok "$1"; return; fi
  case "$3" in
    a) bad "$1"; FAIL_A=$((FAIL_A+1)) ;;
    b) bad "$1 $c_dim(للوضع ب)$c_0"; FAIL_B=$((FAIL_B+1)) ;;
    o) warn "$1 $c_dim(اختياري — الصيغ التي تحتاجه تُرفض صراحةً ولا تُبتلع)$c_0"
       FAIL_O=$((FAIL_O+1)) ;;
  esac
}
chk "python3 ≥ 3.10"          have_python a
chk "PyYAML"                  have_yaml   a
chk "sqlite3 مع FTS5"         have_fts5   a
chk "قراءة PDF"               have_pdf    o
chk "التعرّف الضوئي العربي"    have_ocr_ara o
if [ "$MODE" = b ]; then
  chk "Linux"                 is_linux    b
  chk "bwrap"                 have_bwrap  b
  chk "node ≥ 24.11"          have_node   b
fi

# ── الاختبارات ────────────────────────────────────────────────────────
T_PASS=0; T_FAIL=0
if [ "$SKIP_TESTS" -eq 0 ]; then
  head_ "٦· الاختبارات"
  run_t() {  # الاسم، الأمر
    if bash -c "$2" >/tmp/_setup_test.log 2>&1; then ok "$1"; T_PASS=$((T_PASS+1))
    else bad "$1"; T_FAIL=$((T_FAIL+1)); tail -10 /tmp/_setup_test.log | sed 's/^/      /'; fi
  }
  run_t "سلامة الحزمة وتماسك الخط" "python3 scripts/validate.py"
  for t in tools/tests/test_*.py; do
    run_t "$(basename "$t" .py)" "python3 '$t'"
  done
  run_t "الاختبار الشامل من طرف إلى طرف" "./scripts/e2e-test.sh"
fi

# فحص العزل ليس اختبار شفرة بل اختبار بيئة: يفشل لأن صدفتك تحمل رمز GitHub
# مثلًا، لا لأن في المكتب عطبًا. فيُحسب متطلبًا للوضع (ب) لا اختبارًا فاشلًا —
# وإلا بدا المشروع مكسورًا بينما الأدوات كلها تعمل.
if [ "$MODE" = b ] && [ -f config/env.local ]; then
  head_ "٧· العزل والتحصين"
  if bash -c 'set -a; . ./config/env.local; set +a; ./scripts/verify-isolation.sh' \
       >/tmp/_setup_iso.log 2>&1; then
    ok "البيئة محصّنة"
  else
    bad "البيئة غير محصّنة $c_dim(للوضع ب)$c_0"; FAIL_B=$((FAIL_B+1))
    sed -e 's/\x1b\[[0-9;]*m//g' /tmp/_setup_iso.log | grep -E '✗|!' | sed 's/^/    /'
    dim "التفصيل: ./scripts/verify-isolation.sh"
  fi
fi

# ── الخلاصة ───────────────────────────────────────────────────────────
printf '\n%s%s%s\n' "$c_dim" "──────────────────────────────────────────────────────────" "$c_0"
[ "$SKIP_TESTS" -eq 0 ] && printf '  الاختبارات: %s%d ناجح%s   %s\n' \
  "$c_grn" "$T_PASS" "$c_0" \
  "$([ "$T_FAIL" -gt 0 ] && printf '%s%d فاشل%s' "$c_red" "$T_FAIL" "$c_0" || echo '')"

if [ "$FAIL_A" -gt 0 ] || [ "$T_FAIL" -gt 0 ]; then
  printf '\n%s✗ التثبيت غير مكتمل: %d متطلب ناقص للوضع (أ)، %d اختبار فاشل.%s\n' \
    "$c_red" "$FAIL_A" "$T_FAIL" "$c_0"
  [ ${#MANUAL[@]} -gt 0 ] && { printf '  يحتاج تدخلك:\n'; printf '    • %s\n' "${MANUAL[@]}"; }
  printf '\n'
  exit 1
fi

printf '\n%s✓ الأدوات جاهزة%s — المدونة والبحث والبوابة وفحص العقود وإصدار Word.\n' "$c_grn" "$c_0"
if [ "$FAIL_O" -gt 0 ]; then
  printf '%s  %d خلفية اختيارية ناقصة%s — المستندات التي تحتاجها تُرفض صراحةً\n' \
    "$c_yel" "$FAIL_O" "$c_0"
  printf '  ولا تُعالَج بنص فارغ يُبنى عليه. بقية الصيغ تعمل بالمكتبة القياسية.\n'
fi
if [ ${#MANUAL[@]} -gt 0 ]; then
  printf '\n%s  يحتاج تدخلك:%s\n' "$c_yel" "$c_0"
  printf '    • %s\n' "${MANUAL[@]}"
fi
if [ "$MODE" = b ] && [ "$FAIL_B" -gt 0 ]; then
  printf '\n%s  %d متطلب ناقص للوضع (ب) — المنصة والوكلاء.%s\n' "$c_yel" "$FAIL_B" "$c_0"
  printf '  عالجه قبل تشغيل Paperclip. الأدوات تعمل الآن بدونه.\n'
fi
cat <<'NEXT'

  الخطوة التالية — ابنِ المدونة القانونية، فهي شرط كل ما بعدها:

    python3 scripts/build-corpus.py --plan       # ماذا سيفعل قبل أن يفعله
    python3 scripts/build-corpus.py --discover   # رشّح روابط التشريعات
    python3 scripts/build-corpus.py              # نزّل واستورد وعايِر
    python3 tools/corpus/corpus_cli.py stats     # ينتهي بـ«الخطوة التالية»

  الدليل الكامل:  docs/tashghil.md
NEXT
exit 0
