#!/usr/bin/env bash
# التحقق من عزل المكتب — يفشل بصوت عالٍ عند أي قناة تسريب.
# Verifies the local-only posture. Exit 0 = isolated, 1 = a leak channel is open.
#
#   ./scripts/verify-isolation.sh            # فحص البيئة والإعداد
#   ./scripts/verify-isolation.sh --runtime  # + فحص الخادم الحي
set -uo pipefail

FAIL=0
WARN=0
PAPERCLIP_CONFIG="${PAPERCLIP_HOME:-$HOME/.paperclip}/instances/${PAPERCLIP_INSTANCE_ID:-default}/config.json"

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
ok()   { printf '  %s✓%s %s\n' "$c_grn" "$c_off" "$1"; }
bad()  { printf '  %s✗%s %s\n' "$c_red" "$c_off" "$1"; FAIL=$((FAIL+1)); }
warn() { printf '  %s!%s %s\n' "$c_yel" "$c_off" "$1"; WARN=$((WARN+1)); }
head_() { printf '\n%s%s%s\n' "$c_dim" "$1" "$c_off"; }

printf '\n══ التحقق من عزل المكتب / Office isolation check ══\n'

# ── 1. متغيرات الإطفاء المطلوبة ───────────────────────────────────────
head_ "1. مفاتيح الإطفاء المطلوبة"
require_val() {
  local var=$1 want=$2 got=${!1:-}
  if [ "$got" = "$want" ]; then ok "$var=$want"
  else bad "$var يجب أن يكون '$want' (القيمة الحالية: '${got:-<غير معرّف>}')"; fi
}
require_val PAPERCLIP_TELEMETRY_DISABLED 1
require_val DO_NOT_TRACK 1
require_val PAPERCLIP_UPDATE_CHECK 0

# ── 2. متغيرات يجب ألا تكون معرّفة ────────────────────────────────────
head_ "2. قنوات خارجية يجب أن تبقى مغلقة"
FORBIDDEN=(
  SENTRY_DSN SENTRY_DSN_BACKEND SENTRY_DSN_FRONTEND
  OTEL_EXPORTER_OTLP_ENDPOINT
  PAPERCLIP_TELEMETRY_ENDPOINT PAPERCLIP_TELEMETRY_BACKEND_URL
  PAPERCLIP_FEEDBACK_EXPORT_BACKEND_URL
  PAPERCLIP_CLOUD_TENANT_SERVER_TOKEN PAPERCLIP_MANAGED_CONFIG
  GITHUB_TOKEN GH_TOKEN PAPERCLIP_GITHUB_TOKEN PAPERCLIP_GIT_TOKEN
)
for v in "${FORBIDDEN[@]}"; do
  if [ -n "${!v:-}" ]; then bad "$v معرّف — يفتح قناة خارجية"; fi
done
# أي متغير بادئته PAPERCLIP_ID_CONNECTOR_
if env | grep -q '^PAPERCLIP_ID_CONNECTOR_'; then
  bad "PAPERCLIP_ID_CONNECTOR_* معرّف — تسجيل سحابي مفعّل"
fi
[ "$FAIL" -eq 0 ] && ok "لا قناة خارجية مفتوحة عبر البيئة"

# ── 3. التخزين وقاعدة البيانات محليان ─────────────────────────────────
head_ "3. التخزين المحلي"
if [ -n "${PAPERCLIP_STORAGE_PROVIDER:-}" ] && [ "${PAPERCLIP_STORAGE_PROVIDER}" != "local_disk" ]; then
  bad "PAPERCLIP_STORAGE_PROVIDER=${PAPERCLIP_STORAGE_PROVIDER} — يجب أن يكون local_disk"
else ok "التخزين على القرص المحلي"; fi
if [ -n "${DATABASE_URL:-}" ]; then
  case "$DATABASE_URL" in
    *localhost*|*127.0.0.1*) ok "قاعدة البيانات محلية" ;;
    *) bad "DATABASE_URL يشير إلى مضيف غير محلي" ;;
  esac
else ok "Postgres المضمّن محليًا (DATABASE_URL غير معرّف)"; fi

# ── 4. ملف إعداد Paperclip — الفخ المعروف ─────────────────────────────
head_ "4. ملف إعداد Paperclip"
if [ -f "$PAPERCLIP_CONFIG" ]; then
  if grep -Eq '"enabled"[[:space:]]*:[[:space:]]*true' <(python3 - "$PAPERCLIP_CONFIG" <<'PY' 2>/dev/null || true
import json,sys
try: print(json.dumps(json.load(open(sys.argv[1])).get("telemetry",{})))
except Exception: pass
PY
  ); then
    bad "telemetry.enabled=true في $PAPERCLIP_CONFIG — أعاد onboard تفعيلها. متغيرات البيئة تتغلب عليها، لكن صحّح الملف."
  else ok "التليمتري مطفأة في ملف الإعداد"; fi
else
  warn "لم يُنشأ ملف الإعداد بعد ($PAPERCLIP_CONFIG) — شغّل التحقق ثانيةً بعد التثبيت"
fi

# ── 5. أدوات العزل ────────────────────────────────────────────────────
head_ "5. أدوات فرض عزل الشبكة"
if [ "$(uname -s)" != "Linux" ]; then
  bad "النظام $(uname -s) — فرض networkScope يتطلب Linux"
elif command -v bwrap >/dev/null 2>&1; then
  ok "bwrap متاح ($(command -v bwrap)) — عزل الشبكة قابل للفرض"
else
  bad "bwrap غير مثبّت — بدونه لا يوجد عزل شبكي حقيقي. ثبّته: apt install bubblewrap"
fi

# ── 6. الخادم الحي (اختياري) ──────────────────────────────────────────
if [ "${1:-}" = "--runtime" ]; then
  head_ "6. فحص الخادم الحي"
  API="${PAPERCLIP_API_URL:-http://127.0.0.1:3100}"
  if curl -sf --max-time 5 "$API/api/health" >/dev/null 2>&1; then
    ok "الخادم يستجيب على $API"
    LISTEN=$(ss -ltnp 2>/dev/null | grep -E ':(3100|3102)\b' || true)
    if echo "$LISTEN" | grep -qE '0\.0\.0\.0|\[::\]'; then
      bad "الخادم مربوط على كل الواجهات — يجب أن يكون 127.0.0.1 فقط"
    elif [ -n "$LISTEN" ]; then ok "الخادم مربوط على الواجهة المحلية فقط"; fi
  else
    warn "الخادم لا يستجيب على $API — تخطّي الفحص الحي"
  fi
fi

# ── الخلاصة ───────────────────────────────────────────────────────────
printf '\n'
if [ "$FAIL" -gt 0 ]; then
  printf '%s✗ فشل التحقق: %d مشكلة%s — المكتب غير معزول. لا تشغّل قضايا حقيقية.\n\n' "$c_red" "$FAIL" "$c_off"
  exit 1
fi
printf '%s✓ المكتب معزول%s' "$c_grn" "$c_off"
[ "$WARN" -gt 0 ] && printf ' (%d تنبيه)' "$WARN"
printf '\n  المخرجات والقضايا لا تغادر الجهاز.\n'
printf '  الاستثناء الوحيد: نص القضية يمر عبر واجهة Anthropic للاستدلال.\n\n'
exit 0
