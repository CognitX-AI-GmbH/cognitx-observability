# Alert runbook

One section per alerting rule in `docker/prometheus/rules/`. Each alert's
`runbook_url` annotation points at its section, and
`scripts/check_rules.py` fails CI when an alert has no section, or its
section lacks one of the four parts below.

Queries are PromQL for the Prometheus UI (dev: http://127.0.0.1:9090) unless
marked `sql` (cognitx-lite intelligence database) or `sh`.

Delivery path: Prometheus -> Alertmanager (dev: http://127.0.0.1:9093) ->
email (`ALERT_*` settings in `docker/.env`). See
[Delivering alerts](#delivering-alerts) at the end.

---

## ServiceDown

**Meaning**: Prometheus has not been able to scrape `{{ job }}` for 2 minutes.
Either the service is down, or its `/metrics` endpoint is gone.

**First query**: `up == 0`, then open Status -> Targets for the error text
(connection refused = not running; 404 = running without `/metrics`).

**Likely causes**: the container stopped or is restarting; the port in
`docker/prometheus/prometheus.yml` no longer matches the service; a service
that never had `/metrics` (cognitx-lite tools until #1272).

**Remedy**: `docker ps` for the service and restart it. A 404 means a scrape
job for a service without an endpoint: add the endpoint or remove the job.
A retired service: delete its job (see the removed-jobs note in
`prometheus.yml`).

## HighErrorRate

**Meaning**: more than 5% of a service's requests answered 5xx over 5 minutes,
with at least 20 requests in the window.

**First query**: serving: `sum by (http_route) (rate(http_requests_total{http_status_code=~"5.."}[5m]))`;
intelligence: `sum by (endpoint, status) (rate(cognitx_request_errors_total{status=~"5.."}[5m]))`.

**Likely causes**: a dependency down (database, Redis, serving for
intelligence, the model backend for inference); a bad deploy; one endpoint
failing on every call.

**Remedy**: read the service log for the failing route
(`docker logs --since 10m <container>`), fix or roll back the dependency or
the release. One endpoint only: that handler's error, not an outage.

## HighLatencyInference

**Meaning**: p95 of the inference API is over 10 seconds for 5 minutes.

**First query**: `histogram_quantile(0.95, sum by (le, http_route) (rate(http_request_duration_seconds_bucket{job="inference"}[5m])))`

**Likely causes**: the model backend is saturated or cold; long prompts;
a provider slowdown upstream.

**Remedy**: check the backend's queue and GPU utilisation; scale or shed
load; if one route dominates, look at its request sizes.

## HighLatencyAPI

**Meaning**: p95 of the intelligence API, streaming and health endpoints
excluded, is over 2 seconds for 5 minutes.

**First query**: `topk(5, histogram_quantile(0.95, sum by (le, endpoint) (rate(cognitx_request_duration_seconds_bucket[5m]))))`

**Likely causes**: a slow database query behind one endpoint; connection
pool exhaustion; a synchronous call to serving or tools on the request path.

**Remedy**: find the endpoint from the query, then its slow statement
(`sql`: `select query, mean_exec_time from pg_stat_statements order by 2 desc limit 10`);
fix the query or move the work to a background job.

## PrometheusHighMemory

**Meaning**: Prometheus uses more than 2 GB of resident memory for 10 minutes.

**First query**: `topk(10, count by (__name__) ({__name__=~".+"}))` (which metrics carry the series).

**Likely causes**: a label with unbounded values (ids, paths) on a new
metric; retention too long for the host.

**Remedy**: bound the label in the emitting code (the lite collectors use
fixed label sets for this reason); drop the series with a relabel rule
meanwhile; lower `--storage.tsdb.retention.time`.

## PrometheusAlertmanagerMissing

**Meaning**: Prometheus has no Alertmanager. Every alert is evaluated and
delivered to nobody. This was the permanent state until 2026-09-16.

**First query**: `sh`: `curl -s 127.0.0.1:9090/api/v1/alertmanagers`

**Likely causes**: the `alertmanager` container is down; the `alerting:`
block is missing from `prometheus.yml`; Prometheus and Alertmanager are not
on the same compose network.

**Remedy**: `docker compose up -d alertmanager` in `docker/`; confirm
`activeAlertmanagers` lists `alertmanager:9093`.

## PrometheusRuleEvaluationFailures

**Meaning**: a rule group fails to evaluate. Its alerts can never fire while
this lasts.

**First query**: Status -> Rules in the Prometheus UI shows the error on the
failing rule; `sh`: `curl -s 127.0.0.1:9090/api/v1/rules | grep -o '"lastError":"[^"]*"' | sort -u`

**Likely causes**: a many-to-many match after a label change on a metric;
a recording rule producing duplicate series.

**Remedy**: fix the expression, run `make check`, reload Prometheus
(`curl -X POST 127.0.0.1:9090/-/reload`).

## AlertmanagerNotificationsFailing

**Meaning**: Alertmanager tried to deliver an alert and the receiver refused.
Firing alerts are not reaching anyone.

**First query**: `sum by (integration, reason) (increase(alertmanager_notifications_failed_total[15m]))`,
then `sh`: `docker logs --since 15m cognitx-alertmanager`

**Likely causes**: wrong `ALERT_SMTP_SMARTHOST`, bad SMTP credentials,
`ALERT_SMTP_REQUIRE_TLS=true` against a server without STARTTLS (dev
mailpit), the mail server rejecting the sender.

**Remedy**: fix `docker/.env`, then `docker compose up -d --force-recreate alertmanager`
(a restart does not re-read env). Prove it with `make alert-test`.

## UsageLedgerDrift

**Meaning**: cognitx-lite's `usage_events` and cognitx-serving's
`usage_record` disagree by more than 2% for a model, sustained for 2 hours.
Someone is either not billed or billed twice.

**First query**: `max by (model) (cognitx_usage_reconciliation_drift_ratio)`;
`sql`: `select created_at, detail from audit_events where resource_type::text = 'usage_reconciliation' order by created_at desc limit 5`

**Likely causes**: a model call path that bypasses the lite usage sink; a
serving outbox stuck (`inference_usage_outbox_stuck`); different model
names for the same deployment on the two sides.

**Remedy**: compare the per-model counts in the audit row; fix the missing
recorder or unstick the outbox; the next nightly run must report 0.

## UsageReconciliationUnavailable

**Meaning**: the nightly comparison could not read serving's ledger. The
result is UNKNOWN, not clean.

**First query**: `increase(cognitx_usage_reconciliation_unavailable_total[25h])`;
`sh`: `docker logs --since 25h cognitx-lite-intelligence 2>&1 | grep usage_reconcile`

**Likely causes**: serving unreachable from intelligence; the reconcile
credential refused (`/v1/usage/by-model` answers 401/403).

**Remedy**: restore reachability or the credential, then re-run the job
(enqueue `usage_reconcile`) and confirm a `usage_reconciliation` audit row.

## LiteTurnLatencyHigh

**Meaning**: p95 of orchestrator run duration is above 90 seconds for a domain.

**First query**: `cognitx:turn_latency_seconds:p95_5m`

**Likely causes**: model backend slow; a tool loop running many iterations;
sandbox cells timing out and retrying.

**Remedy**: check `cognitx_runtime_run_steps_bucket` for iteration growth
and the serving latency alerts; slow tools show in
`cognitx_tool_call_duration_seconds_bucket`.

## LiteTickLatenessHigh

**Meaning**: automation ticks run more than 2 minutes after their scheduled
slot (p95 over 1h).

**First query**: `cognitx:tick_lateness_seconds:p95_1h` and
`cognitx:bg_job_start_lag_seconds:p95_5m`

**Likely causes**: the planner is not leader anywhere; the background job
runner is saturated; ticks queue behind heavy jobs.

**Remedy**: see "Is the lane running on this replica?" in cognitx-lite
`intelligence/RUNBOOK.md`; add workers or reserve capacity for the lane.

## LiteTickFailureRatioHigh

**Meaning**: more than 20% of automation ticks failed in the last hour (at
least 5 ticks).

**First query**: `sum by (outcome, mode) (increase(cognitx_automation_ticks_total[1h]))`;
`sql`: `select automation_id, status, error from automation_ticks where created_at > now() - interval '1 hour' and status = 'failed' order by created_at desc limit 20`

**Likely causes**: a connector credential expired; a sealed cell broken by a
contract change; a provider outage misclassified as failure.

**Remedy**: follow "My automation stopped" in cognitx-lite
`intelligence/RUNBOOK.md`; re-seal or reconnect as the error says.

## LiteFirstAttemptSuccessLow

**Meaning**: fewer than 70% of tool dispatches succeed on the first attempt
(at least 20 calls in the hour).

**First query**: `topk(10, sum by (tool) (increase(cognitx_tool_call_errors_total[1h])))`

**Likely causes**: drift between the prompt's tool contract and the sandbox
(unknown method, wrong kwarg); a connector returning errors.

**Remedy**: read the failing tool's errors in the turn records; fix the
contract or the connector. A single tool dominating is a connector incident.

## LiteParkRateHigh

**Meaning**: more than half of the automation ticks in the last hour parked
their actions instead of firing.

**First query**: `sum by (event) (increase(cognitx_automation_park_events_total[1h]))`

**Likely causes**: envelopes missing or expired; automations that should be
sealed are not; the trust ceiling parks critical automations by design.

**Remedy**: review the parked manifests on the automations page; approve an
envelope or seal where the owner agrees. See "Sealing" in the lite RUNBOOK.

## LiteBudgetSkips

**Meaning**: at least one automation slot was refused because its workspace
was over its LLM budget.

**First query**: `cognitx:budget_skips:1h`;
`sql`: `select automation_id, skip_reason, created_at from automation_ticks where skip_reason = 'budget' order by created_at desc limit 20`

**Likely causes**: a prose automation costing more per run than planned; the
budget set too low.

**Remedy**: tell the owner the remedy: raise the budget or seal the
automation so its runs cost nothing.

## LiteReconcilerDiscrepancies

**Meaning**: the reconciler found actions fired but not recorded, or
recorded but not fired. The relay ledger and the engine disagree.

**First query**: `sum by (outcome) (increase(cognitx_automation_reconciliations_total[1h]))`

**Likely causes**: a crash between fire and bookkeeping; a second replica
running the planner; a lost job id.

**Remedy**: treat as an incident: compare the relay's `tool_call_logs` with
`automation_ticks` for the named automations and correct the record before
the next run. Never re-fire from here.

## LiteCapacityFailures

**Meaning**: provider or sandbox capacity failures (429, 5xx, timeouts) in the
last 15 minutes.

**First query**: `sum(increase(cognitx_automation_capacity_failures_total[15m]))`

**Likely causes**: model provider outage or rate limit; sandbox pool
exhausted.

**Remedy**: an outage, not a broken fleet: seals are left alone by design.
Check the provider status and the sandbox pool; the capacity streak resumes
the automations on its own.

## LiteBackgroundJobStartLagHigh

**Meaning**: background jobs of one kind start more than 30 seconds after
enqueue (p95 over 5m).

**First query**: `cognitx:bg_job_start_lag_seconds:p95_5m`;
`sql`: `select kind, count(*) from background_jobs where status = 'queued' group by 1 order by 2 desc`

**Likely causes**: too few workers; a long-running kind occupying the pool;
a stuck claim.

**Remedy**: add workers or move the heavy kind to its own pool; orphaned
claims are recovered by the runner (`cognitx_bg_jobs_orphan_recovered_total`).

## LiteLakehouseSnapshotUnreadable

**Meaning**: reading a workspace's lakehouse snapshot failed (phase
`dispatch`: before a cell ran; `resume`: while checking an interrupted
call). The call is then reported as unverifiable instead of re-run: safe,
and visible to the user.

**First query**: `sum by (phase) (increase(cognitx_runtime_lakehouse_snapshot_unreadable_total[15m]))`;
`sh`: `docker logs --since 15m cognitx-lite-tools 2>&1 | grep -i lakehouse/snapshot`

**Likely causes**: tools unreachable from intelligence; the DuckLake catalog
database down; the snapshot endpoint erroring for one workspace.

**Remedy**: restore tools / the catalog; check
`GET /api/v1/execute/lakehouse/snapshot` on tools for the workspace.
Interrupted turns in the window need a human look at the data.

## LiteDispatchResolvedUnknown

**Meaning**: resumed turns reported interrupted calls as UNKNOWN (snapshot or
external effects unverifiable) instead of re-running them.

**First query**: `sum by (reason) (increase(cognitx_runtime_dispatch_resolutions_total{decision="report"}[1h]))`;
`sql`: `select turn_id, tool_name, resolution from turn_dispatches where state = 'unknown' order by updated_at desc limit 20`

**Likely causes**: the same as LiteLakehouseSnapshotUnreadable (reason
`lakehouse_unknown`); the relay effects read failing (reason
`effects_unknown`).

**Remedy**: fix the unreadable dependency; the affected users were told the
call was not repeated, so nothing needs undoing, but check the data those
cells touch.

## LiteServingCredentialRejected

**Meaning**: cognitx-serving answered 401/403 to a PLATFORM credential on
the request path. Every LLM, embedding and rerank call on it fails, and
readiness takes the pod out of the Service for 120 s after each rejection.

**First query**: `sum by (profile) (increase(cognitx_serving_auth_rejections_total[10m]))`;
`sh`: `curl -s 127.0.0.1:8004/health-check/ready`

**Likely causes**: the serving API key was revoked or rotated without
updating `SERVING_API_KEY` / `SERVING_AUTH_PROFILES`; a key without the
required scopes.

**Remedy**: mint a key with the right scopes in serving, update the secret,
force-recreate intelligence (a restart does not re-read env files).

## LiteReadinessDimensionFailing

**Meaning**: one readiness dimension (`check` label: database, db_role,
alembic, serving_credential, redis) fails on a pod that is still scraped.
The pod is NotReady because of it.

**First query**: `min by (instance, check) (cognitx_readiness_check_ok) == 0`;
`sh`: `curl -s 127.0.0.1:8004/health-check/ready` names the error.

**Likely causes**: `alembic`: schema drift after a pull (migrate); `db_role`:
the app runs as the owner role; `serving_credential`: see
LiteServingCredentialRejected; `redis` / `database`: the dependency is down.

**Remedy**: fix the named dimension; the gauge returns to 1 on the next
probe.

## LiteServingCredentialUnverified

**Meaning**: for 15 minutes the readiness probe could not reach serving's
`/v1/models`, so the credential dimension says ok without proof.

**First query**: `max by (instance) (cognitx_readiness_check_unverified{check="serving_credential"})`

**Likely causes**: serving down or unreachable from intelligence;
`SERVING_URL` wrong.

**Remedy**: restore serving reachability; chat is failing meanwhile unless a
fallback provider is configured.

## LiteParkMailVolumeHigh

**Meaning**: more than 20 approval mails about parked manifests went out in
the last hour. An inbox like that gets filtered and the mail that matters
is lost (193 in one live day before the cooldown existed).

**First query**: `sum by (outcome) (increase(cognitx_automation_park_emails_total[1h]))`

**Likely causes**: `AUTOMATION_PARK_NOTIFY_COOLDOWN_S` set to 0; many
automations parking on every run.

**Remedy**: restore the cooldown; for the parking automations, approve an
envelope or seal them (see LiteParkRateHigh).

## LiteParkMailNotSent

**Meaning**: a manifest parked and the approval mail was not sent. The park
is visible only in the app.

**First query**: `sum by (outcome) (increase(cognitx_automation_park_emails_total[1h]))`;
`sh`: `docker logs --since 1h cognitx-lite-intelligence 2>&1 | grep -i notify`

**Likely causes**: SMTP settings of intelligence wrong or the mail server
down; the owner has no address.

**Remedy**: fix the mail settings; tell the owners of parked automations
directly until mail works.

## AlertPipelineTest

**Meaning**: the synthetic alert from `make alert-test`. It proves that a rule
reaches Alertmanager and Alertmanager reaches the mailbox. It exists only
while the test runs (`docker/prometheus/rules/synthetic.yml`, gitignored).

**First query**: `ALERTS{alertname="AlertPipelineTest"}`

**Likely causes**: someone is running `make alert-test`; a leftover
`synthetic.yml` if it keeps firing.

**Remedy**: none while the test runs; a leftover file: `make alert-test-clean`.

---

## Delivering alerts

`docker/alertmanager/alertmanager.yml.tmpl` is rendered at container start
from `docker/.env`:

| setting | dev default | meaning |
|---|---|---|
| `ALERT_EMAIL_TO` | `oncall@cognitx.local` | recipient(s), comma separated |
| `ALERT_EMAIL_FROM` | `alertmanager@cognitx.local` | sender |
| `ALERT_SMTP_SMARTHOST` | `host.docker.internal:1125` | host:port; dev = the cognitx-lite mailpit (UI http://127.0.0.1:8125) |
| `ALERT_SMTP_AUTH_USERNAME` / `ALERT_SMTP_AUTH_PASSWORD` | empty | SMTP login, empty for mailpit |
| `ALERT_SMTP_REQUIRE_TLS` | `false` | `true` for any real mail server |

Critical alerts repeat every hour, warnings every 4 hours, info never
mails. `make alert-test` drops an always-firing rule, waits for the mail in
mailpit and removes the rule again.

GKE: cognitx-lite `deploy/gke` holds no monitoring manifests (no
Prometheus, Alertmanager or ServiceMonitor), so these rules do not run
there yet. Porting them means a PrometheusRule per file in this directory
and an AlertmanagerConfig with the same route, under Managed Service for
Prometheus or kube-prometheus.
