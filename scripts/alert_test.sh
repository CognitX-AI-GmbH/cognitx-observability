#!/bin/sh
# Synthetic breach: prove a firing rule reaches the mailbox.
#
#   Prometheus rule -> Alertmanager -> SMTP -> mailpit
#
# Drops an always-firing rule into docker/prometheus/rules/synthetic.yml
# (gitignored), reloads Prometheus, waits for the mail in mailpit's API,
# then removes the rule and reloads again. Exit 0 only when the mail
# arrived.
#
# PROM_URL     default http://127.0.0.1:9090
# MAILPIT_URL  default http://127.0.0.1:8125  (cognitx-lite mailpit UI/API)
# TIMEOUT_S    default 180
set -eu

here=$(cd "$(dirname "$0")/.." && pwd)
rule="$here/docker/prometheus/rules/synthetic.yml"
prom="${PROM_URL:-http://127.0.0.1:9090}"
mailpit="${MAILPIT_URL:-http://127.0.0.1:8125}"
timeout="${TIMEOUT_S:-180}"
stamp=$(date -u +%Y%m%dT%H%M%SZ)

cleanup() {
  rm -f "$rule"
  curl -fsS -X POST "$prom/-/reload" >/dev/null 2>&1 || true
}

if [ "${1:-}" = "--clean" ]; then
  cleanup
  echo "alert-test: synthetic rule removed"
  exit 0
fi

trap cleanup EXIT INT TERM

cat > "$rule" <<YAML
# Written by scripts/alert_test.sh at $stamp; removed when it exits.
groups:
  - name: synthetic_pipeline_test
    rules:
      - alert: AlertPipelineTest
        expr: vector(1)
        labels:
          severity: test
          run: "$stamp"
        annotations:
          summary: "Synthetic alert pipeline test $stamp"
          description: "Proves Prometheus -> Alertmanager -> email. Safe to ignore."
          runbook_url: "https://github.com/CognitX-AI-GmbH/cognitx-observability/blob/main/docs/runbooks/alerts.md#alertpipelinetest"
YAML

curl -fsS -X POST "$prom/-/reload" >/dev/null
echo "alert-test: rule loaded (run=$stamp), waiting up to ${timeout}s for the mail"

elapsed=0
while [ "$elapsed" -lt "$timeout" ]; do
  found=$(curl -fsS "$mailpit/api/v1/search?query=$stamp" 2>/dev/null || true)
  case "$found" in
    *'"messages_count":0'*|'') ;;
    *)
      echo "alert-test: DELIVERED after ${elapsed}s"
      printf '%s\n' "$found"
      exit 0
      ;;
  esac
  sleep 5
  elapsed=$((elapsed + 5))
done

echo "alert-test: no mail with run=$stamp after ${timeout}s" >&2
curl -fsS "$prom/api/v1/alerts" >&2 || true
exit 1
