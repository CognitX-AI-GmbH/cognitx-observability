#!/usr/bin/env python3
"""Check the Prometheus rule files for the two failure classes promtool misses.

1. A rule that reads a metric nobody exports. promtool accepts any name, and
   an absent series is not an error, it is silence: UsageLedgerDrift read
   ``usage_reconciliation_drift_ratio`` while the service exported
   ``cognitx_usage_reconciliation_drift_ratio``, and HighErrorRate read
   ``cognitx_http_requests_total``, which no service has ever exported.
   Every metric an expression names must be listed in
   docker/prometheus/metrics-catalog.txt (with the code that emits it) or be
   a recording rule defined in the rule files.

2. An alert without a runbook. Every alerting rule must carry a
   ``runbook_url`` annotation pointing at RUNBOOK_BASE#<anchor>, the anchor
   must be a heading in docs/runbooks/alerts.md, and that section must say
   what the alert means, the first query to run, the likely causes and the
   remedy.

Usage: python3 scripts/check_rules.py            (CI)
       python3 scripts/check_rules.py --self-test
       python3 scripts/check_rules.py --live URL (also: every catalog entry
                                                  has a series on that
                                                  Prometheus; informational)
Requires PyYAML.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = ROOT / "docker" / "prometheus" / "rules"
CATALOG = ROOT / "docker" / "prometheus" / "metrics-catalog.txt"
RUNBOOK = ROOT / "docs" / "runbooks" / "alerts.md"
RUNBOOK_BASE = (
    "https://github.com/CognitX-AI-GmbH/cognitx-observability/blob/main/"
    "docs/runbooks/alerts.md#"
)
REQUIRED_PARTS = ("**Meaning**", "**First query**", "**Likely causes**", "**Remedy**")

# PromQL words that look like identifiers but are not metric names.
_KEYWORDS = {
    "and", "or", "unless", "by", "without", "on", "ignoring", "group_left",
    "group_right", "offset", "bool", "atan2", "inf", "nan", "start", "end",
}
_IDENT = re.compile(r"[A-Za-z_:][A-Za-z0-9_:]*")


def metric_names(expr: str) -> set[str]:
    """The metric names an expression selects (crude, but PromQL-aware
    enough for rule files: strings, label matchers, grouping clauses,
    ranges, durations, numbers and function calls are removed first)."""
    s = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`[^`]*`', '""', expr)
    s = re.sub(r"\{[^}]*\}", " ", s)
    s = re.sub(r"\[[^\]]*\]", " ", s)
    s = re.sub(
        r"\b(by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)", " ", s
    )
    s = re.sub(r"\boffset\s+\S+", " ", s)
    names: set[str] = set()
    for m in _IDENT.finditer(s):
        word = m.group(0)
        start = m.start()
        if start > 0 and (s[start - 1].isdigit() or s[start - 1] == "."):
            continue  # 2e9, 0.5, 5m tails
        rest = s[m.end():].lstrip()
        if rest.startswith("("):
            continue  # function call or aggregation
        if word.lower() in _KEYWORDS:
            continue
        names.add(word)
    return names


def load_rules() -> list[tuple[str, dict]]:
    out = []
    for path in sorted(RULES_DIR.glob("*.yml")):
        doc = yaml.safe_load(path.read_text()) or {}
        for group in doc.get("groups") or []:
            for rule in group.get("rules") or []:
                out.append((path.name, rule))
    return out


def load_catalog() -> set[str]:
    names = set()
    for n, line in enumerate(CATALOG.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            raise SystemExit(f"{CATALOG.name}:{n}: '{parts[0]}' has no source (name  source)")
        names.add(parts[0])
    return names


def slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation dropped, spaces -> '-'."""
    text = heading.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def runbook_sections() -> dict[str, str]:
    sections: dict[str, str] = {}
    current = None
    for line in RUNBOOK.read_text().splitlines():
        m = re.match(r"#{2,3}\s+(.*)", line)
        if m:
            current = slug(m.group(1))
            sections[current] = ""
        elif current is not None:
            sections[current] += line + "\n"
    return sections


def check() -> list[str]:
    errors: list[str] = []
    rules = load_rules()
    catalog = load_catalog()
    recorded = {r["record"] for _, r in rules if "record" in r}
    sections = runbook_sections()
    alerts = 0
    for fname, rule in rules:
        name = rule.get("alert") or rule.get("record")
        for metric in sorted(metric_names(str(rule.get("expr", "")))):
            if metric not in catalog and metric not in recorded:
                errors.append(
                    f"{fname}: {name}: metric '{metric}' is not in "
                    f"{CATALOG.relative_to(ROOT)} and is not a recording rule"
                )
        if "alert" not in rule:
            continue
        alerts += 1
        url = (rule.get("annotations") or {}).get("runbook_url", "")
        if not url:
            errors.append(f"{fname}: {name}: no runbook_url annotation")
            continue
        if not url.startswith(RUNBOOK_BASE):
            errors.append(f"{fname}: {name}: runbook_url must start with {RUNBOOK_BASE}")
            continue
        anchor = url[len(RUNBOOK_BASE):]
        body = sections.get(anchor)
        if body is None:
            errors.append(f"{fname}: {name}: anchor '#{anchor}' is not a heading in {RUNBOOK.name}")
            continue
        missing = [p for p in REQUIRED_PARTS if p not in body]
        if missing:
            errors.append(f"{fname}: {name}: runbook section '#{anchor}' lacks {', '.join(missing)}")
    if not errors:
        print(f"ok: {len(rules)} rules ({alerts} alerts), every metric catalogued, every alert has a runbook")
    return errors


def live(url: str) -> None:
    with urllib.request.urlopen(f"{url.rstrip('/')}/api/v1/label/__name__/values") as r:
        present = set(json.load(r)["data"])
    absent = sorted(load_catalog() - present)
    print(f"{len(absent)} catalogued metric(s) have no series on {url} "
          "(expected for counters that never moved: OTEL exports on first measurement):")
    for name in absent:
        print(f"  {name}")


def self_test() -> None:
    cases = {
        'sum by (service) (rate(http_requests_total{code=~"5.."}[5m])) > 0.05': {"http_requests_total"},
        "max_over_time(cognitx_usage_reconciliation_drift_ratio[2h]) > 0.02": {
            "cognitx_usage_reconciliation_drift_ratio"
        },
        "up == 0": {"up"},
        "process_resident_memory_bytes{job=\"prometheus\"} > 2e9": {"process_resident_memory_bytes"},
        "cognitx:park_rate:1h > 0.5 and sum(increase(cognitx_automation_ticks_total[1h])) >= 5": {
            "cognitx:park_rate:1h",
            "cognitx_automation_ticks_total",
        },
        "histogram_quantile(0.95, sum by (le, kind) (rate(x_bucket[5m])))": {"x_bucket"},
        "a / on (service) group_left (team) b offset 5m": {"a", "b"},
        "sum(increase(c_total[1h])) or vector(0)": {"c_total"},
    }
    for expr, want in cases.items():
        got = metric_names(expr)
        assert got == want, f"{expr!r}: {got} != {want}"
    assert slug("UsageLedgerDrift") == "usageledgerdrift"
    assert slug("Service down: what now?") == "service-down-what-now"
    print("self-test ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    if "--live" in sys.argv:
        live(sys.argv[sys.argv.index("--live") + 1])
        sys.exit(0)
    self_test()
    problems = check()
    for p in problems:
        print(f"ERROR {p}")
    sys.exit(1 if problems else 0)
