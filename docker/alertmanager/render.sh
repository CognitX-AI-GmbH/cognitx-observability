#!/bin/sh
# Render alertmanager.yml from the template and exec Alertmanager.
# Plain sh + sed: the prom/alertmanager image is busybox and has no envsubst.
set -eu

: "${ALERT_EMAIL_TO:=oncall@cognitx.local}"
: "${ALERT_EMAIL_FROM:=alertmanager@cognitx.local}"
: "${ALERT_SMTP_SMARTHOST:=host.docker.internal:1125}"
: "${ALERT_SMTP_AUTH_USERNAME:=}"
: "${ALERT_SMTP_AUTH_PASSWORD:=}"
: "${ALERT_SMTP_REQUIRE_TLS:=false}"

case "$ALERT_SMTP_REQUIRE_TLS" in
  true|false) ;;
  *) echo "render.sh: ALERT_SMTP_REQUIRE_TLS must be true or false" >&2; exit 1 ;;
esac

# Escape the sed replacement metacharacters (& \ |) in the values.
esc() { printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'; }

out="${ALERTMANAGER_CONFIG_OUT:-/tmp/alertmanager.yml}"
umask 077
sed \
  -e "s|\${ALERT_EMAIL_TO}|$(esc "$ALERT_EMAIL_TO")|g" \
  -e "s|\${ALERT_EMAIL_FROM}|$(esc "$ALERT_EMAIL_FROM")|g" \
  -e "s|\${ALERT_SMTP_SMARTHOST}|$(esc "$ALERT_SMTP_SMARTHOST")|g" \
  -e "s|\${ALERT_SMTP_AUTH_USERNAME}|$(esc "$ALERT_SMTP_AUTH_USERNAME")|g" \
  -e "s|\${ALERT_SMTP_AUTH_PASSWORD}|$(esc "$ALERT_SMTP_AUTH_PASSWORD")|g" \
  -e "s|\${ALERT_SMTP_REQUIRE_TLS}|$ALERT_SMTP_REQUIRE_TLS|g" \
  /etc/alertmanager/alertmanager.yml.tmpl > "$out"

[ "${1:-}" = "--render-only" ] && exit 0

exec /bin/alertmanager \
  --config.file="$out" \
  --storage.path=/alertmanager \
  --web.listen-address=:9093 \
  "$@"
