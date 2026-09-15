import { describe, expect, it } from "vitest";

import { aqi, category, correctPm25, nowcast, pyRound } from "../src/lib/epa.ts";

describe("aqi", () => {
  it("hits EPA breakpoint edges", () => {
    expect(aqi("pm2_5", 0)).toBe(0);
    expect(aqi("pm2_5", 9.0)).toBe(50);
    expect(aqi("pm2_5", 35.4)).toBe(100);
    expect(aqi("pm2_5", 55.4)).toBe(150);
    expect(aqi("pm10", 54)).toBe(50);
    expect(aqi("pm10", 154)).toBe(100);
  });

  it("clamps negatives, caps the top, passes null through", () => {
    expect(aqi("pm2_5", -5)).toBe(0);
    expect(aqi("pm2_5", 9999)).toBe(500);
    expect(aqi("pm2_5", null)).toBeNull();
  });

  it("maps AQI to EPA categories", () => {
    expect(category(50).label).toBe("Good");
    expect(category(75).label).toBe("Moderate");
    expect(category(200).label).toBe("Unhealthy");
    expect(category(null).label).toBe("Unknown");
  });
});

describe("nowcast", () => {
  it("needs at least two values and handles a constant series", () => {
    expect(nowcast([])).toBeNull();
    expect(nowcast([10])).toBeNull();
    expect(nowcast([20, 20, 20, 20])).toBeCloseTo(20, 6);
  });

  it("weights the recent spike", () => {
    const nc = nowcast([10, 10, 10, 100]);
    expect(nc).not.toBeNull();
    expect(nc!).toBeGreaterThan(50);
  });
});

describe("correctPm25", () => {
  it("applies the EPA/Barkjohn correction", () => {
    expect(correctPm25(100, 50)).toBe(53.8);
    expect(correctPm25(null, 50)).toBeNull();
  });
});

describe("pyRound", () => {
  it("matches CPython banker's rounding on the true value", () => {
    expect(pyRound(0.5)).toBe(0);
    expect(pyRound(1.5)).toBe(2);
    expect(pyRound(2.5)).toBe(2);
    expect(pyRound(2.675, 2)).toBeCloseTo(2.67, 6); // the scaled-int pitfall; epa.ts handles it
  });
});
