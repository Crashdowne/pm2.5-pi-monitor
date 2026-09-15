// Parity guard: the TS EPA port (src/lib/epa.ts) must match the core Python `pm25.aqi`
// exactly. Golden values are generated from pm25.aqi by probes/gen_golden.py and pinned
// in probes/golden.json, so this runs in CI without Python. Regenerate the golden after
// changing src/pm25/aqi.py:  npm run probe:golden
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { aqi, category, correctPm25, nowcast } from "../src/lib/epa.ts";

const here = dirname(fileURLToPath(import.meta.url));
const golden = JSON.parse(readFileSync(join(here, "..", "probes", "golden.json"), "utf8")) as {
  aqi_pm2_5: [number | null, number | null][];
  aqi_pm10: [number | null, number | null][];
  category: [number | null, string, string][];
  nowcast: [(number | null)[], number | null][];
  correct: [number | null, number | null, number | null][];
};

describe("EPA parity with pm25.aqi (Python golden values)", () => {
  it("aqi(pm2_5) matches exactly across breakpoints", () => {
    for (const [c, want] of golden.aqi_pm2_5) expect(aqi("pm2_5", c)).toBe(want);
  });

  it("aqi(pm10) matches exactly across breakpoints", () => {
    for (const [c, want] of golden.aqi_pm10) expect(aqi("pm10", c)).toBe(want);
  });

  it("category label + color match exactly", () => {
    for (const [a, label, color] of golden.category) {
      const cat = category(a);
      expect(cat.label).toBe(label);
      expect(cat.color).toBe(color);
    }
  });

  it("nowcast matches to full double precision", () => {
    for (const [seq, want] of golden.nowcast) {
      const got = nowcast(seq);
      if (want === null) expect(got).toBeNull();
      else expect(got).toBeCloseTo(want, 9);
    }
  });

  it("correct_pm25 matches exactly (1-decimal, banker's rounding)", () => {
    for (const [pm, rh, want] of golden.correct) {
      const got = correctPm25(pm, rh);
      if (want === null) expect(got).toBeNull();
      else expect(got).toBeCloseTo(want, 6);
    }
  });
});
