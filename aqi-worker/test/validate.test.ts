import { describe, expect, it } from "vitest";

import { validateRecord, validateSensorId } from "../src/validate.ts";

const NOW = 1_800_000_000;

describe("validateSensorId", () => {
  it("accepts valid ids", () => {
    expect(validateSensorId("default")).toBe(true);
    expect(validateSensorId("sensor-a.1_2")).toBe(true);
  });
  it("rejects bad ids", () => {
    expect(validateSensorId("")).toBe(false);
    expect(validateSensorId("-leading")).toBe(false);
    expect(validateSensorId("has space")).toBe(false);
    expect(validateSensorId("x".repeat(65))).toBe(false);
  });
});

describe("validateRecord", () => {
  it("cleans a valid record and defaults missing cols to null", () => {
    const r = validateRecord({ ts: NOW - 10, pm2_5: 12.3, rh: 50 }, NOW);
    expect(r).not.toBeNull();
    expect(r!.ts).toBe(NOW - 10);
    expect(r!.pm2_5).toBe(12.3);
    expect(r!.rh).toBe(50);
    expect(r!.pm10).toBeNull();
    expect(r!.pm2_5_corr).toBeNull();
  });
  it("rejects non-integer / out-of-window ts", () => {
    expect(validateRecord({ ts: 1.5 }, NOW)).toBeNull();
    expect(validateRecord({ ts: 100 }, NOW)).toBeNull(); // before TS_MIN
    expect(validateRecord({ ts: NOW + 999999 }, NOW)).toBeNull(); // too far in the future
    expect(validateRecord({}, NOW)).toBeNull();
  });
  it("rejects out-of-range and non-finite values", () => {
    expect(validateRecord({ ts: NOW, pm2_5: 99999 }, NOW)).toBeNull();
    expect(validateRecord({ ts: NOW, rh: -1 }, NOW)).toBeNull();
    expect(validateRecord({ ts: NOW, temp: 999 }, NOW)).toBeNull();
    expect(validateRecord({ ts: NOW, pm2_5: "x" }, NOW)).toBeNull();
    expect(validateRecord({ ts: NOW, pm2_5: true }, NOW)).toBeNull();
    expect(validateRecord({ ts: NOW, pm2_5: Infinity }, NOW)).toBeNull();
  });
  it("rejects non-objects", () => {
    expect(validateRecord(42, NOW)).toBeNull();
    expect(validateRecord([1, 2], NOW)).toBeNull();
    expect(validateRecord(null, NOW)).toBeNull();
  });
});
