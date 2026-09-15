import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { MAX_BODY, MAX_INGEST_ROWS, TS_MIN, VALUE_RANGES, validateRecord } from "../src/validate.ts";

const contract = JSON.parse(
  readFileSync(new URL("../../contracts/ingest_ranges.json", import.meta.url), "utf8"),
) as {
  ts_min: number;
  max_body_bytes: number;
  worker_max_ingest_rows: number;
  value_ranges: Record<string, [number, number]>;
};

describe("ingest contract parity (aqi-worker <-> shared contract)", () => {
  it("value ranges match the shared contract", () => {
    expect(VALUE_RANGES).toEqual(contract.value_ranges);
  });

  it("limits match the shared contract", () => {
    expect(TS_MIN).toBe(contract.ts_min);
    expect(MAX_BODY).toBe(contract.max_body_bytes);
    expect(MAX_INGEST_ROWS).toBe(contract.worker_max_ingest_rows);
  });

  it("accepts an in-range record and rejects out-of-range / stale ts", () => {
    const now = 1_700_000_000;
    expect(validateRecord({ ts: now, pm2_5: 12.3, pm10: 20 }, now)).not.toBeNull();
    expect(validateRecord({ ts: now, pm2_5: 99999 }, now)).toBeNull();
    expect(validateRecord({ ts: contract.ts_min - 1, pm2_5: 5 }, now)).toBeNull();
  });
});
