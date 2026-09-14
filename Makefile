# Rules are code: lint them before they reach a running Prometheus.
# (promtool check config needs the container paths; Prometheus validates
# the config itself on every reload, and refuses a broken one.)
.PHONY: check
check:
	promtool check rules docker/prometheus-alerts.yml docker/prometheus-lite-slo.yml
