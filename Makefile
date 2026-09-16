# Rules and dashboards are code: lint them before they reach a running
# Prometheus or Grafana. Prometheus validates its config on every reload
# and refuses a broken one; Grafana does NOT (it renders a broken panel),
# which is why check_dashboards.py exists; promtool accepts a rule that
# reads a metric nobody exports, which is why check_rules.py exists.
#
# promtool/amtool run from the pinned images, so no local install is needed.
PROM_IMAGE ?= prom/prometheus:v3.10.0
AM_IMAGE ?= prom/alertmanager:v0.28.1
DOCKER_RUN = docker run --rm -v "$(CURDIR)/docker:/w:ro" -w /w

.PHONY: check
check: check-config check-rules test-rules check-alertmanager check-dashboards

.PHONY: check-config
check-config:
	docker run --rm -v "$(CURDIR)/docker/prometheus:/etc/prometheus:ro" \
	  --entrypoint promtool $(PROM_IMAGE) check config /etc/prometheus/prometheus.yml

.PHONY: check-rules
check-rules:
	$(DOCKER_RUN) --entrypoint promtool $(PROM_IMAGE) check rules prometheus/rules/alerts.yml prometheus/rules/lite-slo.yml
	python3 scripts/check_rules.py

.PHONY: test-rules
test-rules:
	$(DOCKER_RUN) --entrypoint promtool $(PROM_IMAGE) test rules prometheus/tests/alerts-test.yml

# Render the template with placeholder values, then let amtool parse it.
.PHONY: check-alertmanager
check-alertmanager:
	docker run --rm -v "$(CURDIR)/docker/alertmanager:/etc/alertmanager:ro" \
	  -e ALERTMANAGER_CONFIG_OUT=/tmp/am.yml --entrypoint /bin/sh $(AM_IMAGE) \
	  -c '/bin/sh /etc/alertmanager/render.sh --render-only && amtool check-config /tmp/am.yml'

.PHONY: check-dashboards
check-dashboards:
	python3 scripts/check_dashboards.py

# Which catalogued metrics have no series on a running Prometheus.
.PHONY: check-metrics-live
check-metrics-live:
	python3 scripts/check_rules.py --live $${PROM_URL:-http://127.0.0.1:9090}

# Synthetic breach: an always-firing rule must arrive in mailpit.
.PHONY: alert-test
alert-test:
	scripts/alert_test.sh

.PHONY: alert-test-clean
alert-test-clean:
	scripts/alert_test.sh --clean
