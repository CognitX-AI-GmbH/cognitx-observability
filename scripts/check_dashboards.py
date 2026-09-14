#!/usr/bin/env python3
"""Dashboards are code: check every one before it reaches a running Grafana.

Grafana accepts almost any JSON and shows a broken panel instead of an
error, so a dashboard with a typo'd metric, a duplicate uid or a panel
that overlaps its neighbour looks fine in review and is useless on the
day somebody needs it. This runs in ``make check`` and in CI.

What it asserts:

* the file parses, and carries a uid, a title and panels;
* uids and titles are unique across the folder (Grafana silently keeps
  one of two dashboards that share a uid);
* every panel has a title, a type and a grid position, and no two panels
  overlap or run past the 24-column grid;
* every non-row panel has at least one target with an expression, and
  every metric an expression reads looks like one this install publishes
  (``cognitx_*``, ``cognitx:*``, ``up``, ``http_server_*``): a metric
  from another install renders empty forever;
* a panel that draws a threshold has one defined.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

DASHBOARDS = pathlib.Path(__file__).resolve().parents[1] / "docker/grafana/dashboards"

#: Metric-name prefixes this install publishes. A name outside them is
#: either a typo or a metric from somebody else's Prometheus.
KNOWN_PREFIXES = ("cognitx_", "cognitx:", "up", "http_server_", "process_", "python_")

#: PromQL functions and keywords that look like metric names to the regex.
_PROMQL_WORDS = {
    "sum", "rate", "increase", "avg", "min", "max", "count", "by", "without",
    "histogram_quantile", "vector", "clamp_min", "clamp_max", "or", "and",
    "unless", "topk", "bottomk", "label_replace", "time", "absent", "delta",
    "irate", "idelta", "quantile", "stddev", "group", "le", "on", "ignoring",
    "offset", "bool", "sum_over_time", "avg_over_time", "max_over_time",
    "min_over_time", "last_over_time", "count_over_time", "predict_linear",
    "deriv", "changes", "resets", "round", "abs", "ceil", "floor", "exp", "ln",
}

_METRIC = re.compile(r"(?<![\w:.])([a-zA-Z_:][a-zA-Z0-9_:]*)\s*(?=[\{\[\(\s\)]|$)")
#: Label lists, not metric names: ``by (route)``, ``without (le)``,
#: ``on (job)``, ``ignoring (instance)``, ``group_left(model)``.
_GROUPING = re.compile(
    r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^()]*\)", re.I
)
#: Label matchers and range selectors hold values, not metric names.
_MATCHER = re.compile(r"\{[^{}]*\}|\[[^\[\]]*\]")


def metric_names(expr: str) -> set[str]:
    """The metric names an expression reads, without its labels."""
    stripped = _MATCHER.sub(" ", _GROUPING.sub(" ", expr))
    out: set[str] = set()
    for m in _METRIC.finditer(stripped):
        name = m.group(1)
        if name in _PROMQL_WORDS or name.isdigit():
            continue
        after = stripped[m.end() : m.end() + 1]
        if after == "(":
            continue  # a function call, known or not
        out.add(name)
    return out


def overlaps(a: dict, b: dict) -> bool:
    ax, ay, aw, ah = a["x"], a["y"], a["w"], a["h"]
    bx, by, bw, bh = b["x"], b["y"], b["w"], b["h"]
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def check(path: pathlib.Path) -> list[str]:
    problems: list[str] = []
    try:
        d = json.loads(path.read_text())
    except Exception as exc:
        return [f"{path.name}: does not parse ({exc})"]
    for key in ("uid", "title", "panels"):
        if not d.get(key):
            problems.append(f"{path.name}: no {key}")
    grids: list[tuple[str, dict]] = []
    for panel in d.get("panels", []):
        title = panel.get("title", "<untitled>")
        for key in ("type", "title", "gridPos"):
            if key not in panel:
                problems.append(f"{path.name}: panel {title!r} has no {key}")
        grid = panel.get("gridPos")
        if isinstance(grid, dict):
            if grid.get("x", 0) + grid.get("w", 0) > 24:
                problems.append(
                    f"{path.name}: panel {title!r} runs past the 24-column grid"
                )
            for other_title, other in grids:
                if overlaps(grid, other):
                    problems.append(
                        f"{path.name}: panel {title!r} overlaps {other_title!r}"
                    )
            grids.append((title, grid))
        if panel.get("type") == "row":
            continue
        targets = panel.get("targets") or []
        if not targets:
            problems.append(f"{path.name}: panel {title!r} has no target")
        for target in targets:
            expr = target.get("expr", "")
            if not expr.strip():
                problems.append(f"{path.name}: panel {title!r} has an empty expression")
                continue
            for name in metric_names(expr):
                if not name.startswith(KNOWN_PREFIXES):
                    problems.append(
                        f"{path.name}: panel {title!r} reads {name!r}, which this "
                        f"install does not publish"
                    )
        defaults = (panel.get("fieldConfig") or {}).get("defaults") or {}
        style = (defaults.get("custom") or {}).get("thresholdsStyle") or {}
        if style.get("mode") in ("line", "area", "dashed") and not defaults.get(
            "thresholds"
        ):
            problems.append(
                f"{path.name}: panel {title!r} draws a threshold it has not defined"
            )
    return problems


def main() -> int:
    files = sorted(DASHBOARDS.glob("*.json"))
    if not files:
        print(f"check_dashboards: no dashboards under {DASHBOARDS}", file=sys.stderr)
        return 1
    problems: list[str] = []
    seen_uid: dict[str, str] = {}
    seen_title: dict[str, str] = {}
    for path in files:
        problems.extend(check(path))
        try:
            d = json.loads(path.read_text())
        except Exception:
            continue
        for field, seen in (("uid", seen_uid), ("title", seen_title)):
            value = d.get(field)
            if value in seen:
                problems.append(
                    f"{path.name}: {field} {value!r} is already used by {seen[value]}"
                )
            elif value:
                seen[value] = path.name
    if problems:
        print(f"check_dashboards: {len(problems)} problem(s)", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(f"check_dashboards: ok ({len(files)} dashboards)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
