# Rules and dashboards are code: lint them before they reach a running
# Prometheus or Grafana. (promtool check config needs the container paths;
# Prometheus validates the config itself on every reload and refuses a
# broken one. Grafana does NOT: it renders a broken panel instead, which
# is why check_dashboards.py exists.)
.PHONY: check
check: check-rules check-dashboards

.PHONY: check-rules
check-rules:
	promtool check rules docker/prometheus-alerts.yml docker/prometheus-lite-slo.yml

.PHONY: check-dashboards
check-dashboards:
	python3 scripts/check_dashboards.py
