#!/usr/bin/env python3
"""Emit golden EPA values from the core `pm25.aqi` (the single source of truth) as JSON.

The TS port in aqi-worker/src/lib/epa.ts must match these exactly; test/parity.test.ts
diffs against the committed probes/golden.json so the port cannot silently drift.

Regenerate after any change to src/pm25/aqi.py:
    PYTHONPATH=../src python3 probes/gen_golden.py > probes/golden.json
"""
from __future__ import annotations

import json

from pm25 import aqi

# Breakpoint edges, interiors, truncation- and rounding-sensitive points, out-of-range.
PM25_INPUTS = [
    None, -5.0, 0.0, 0.05, 4.4, 9.0, 9.05, 9.1, 12.0, 20.35, 35.4, 35.45, 35.5, 45.0,
    55.4, 55.5, 90.7, 125.4, 125.5, 175.3, 225.4, 225.5, 350.0, 500.4, 500.5, 999.9,
]
PM10_INPUTS = [
    None, -5.0, 0.0, 27.0, 54.0, 54.9, 55.0, 100.0, 154.0, 154.9, 155.0, 200.0, 254.0,
    255.0, 300.0, 354.0, 355.0, 424.0, 425.0, 604.0, 700.0,
]
CATEGORY_INPUTS = [None, 0, 25, 50, 51, 75, 100, 101, 150, 151, 200, 201, 300, 301, 500, 501]
NOWCAST_INPUTS = [
    [],
    [10.0],
    [20.0, 20.0, 20.0],
    [10.0, 10.0, 10.0, 100.0],
    [5.0, 50.0, 5.0, 50.0, 5.0, 50.0],
    [0.0, 0.0, 0.0],
    [None, 10.0, 20.0, None, 30.0],
    [float(i) for i in range(20)],  # exercises the 12-value cap + ordering
]
CORRECT_INPUTS = [
    [0.0, 0.0], [100.0, 50.0], [12.3, 55.0], [260.0, 55.0],
    [None, 50.0], [100.0, None], [50.5, 33.3], [9.05, 88.8],
]


def main() -> None:
    golden = {
        "aqi_pm2_5": [[c, aqi.aqi("pm2_5", c)] for c in PM25_INPUTS],
        "aqi_pm10": [[c, aqi.aqi("pm10", c)] for c in PM10_INPUTS],
        "category": [[a, aqi.category(a)["label"], aqi.category(a)["color"]] for a in CATEGORY_INPUTS],
        "nowcast": [[seq, aqi.nowcast(seq)] for seq in NOWCAST_INPUTS],
        "correct": [[pm, rh, aqi.correct_pm25(pm, rh)] for pm, rh in CORRECT_INPUTS],
    }
    print(json.dumps(golden, indent=2))


if __name__ == "__main__":
    main()
