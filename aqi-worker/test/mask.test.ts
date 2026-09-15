import { describe, expect, it } from "vitest";

import { allLevels, describe as describeLevel, levelFor, recommend, severity } from "../src/lib/mask.ts";

const ASTHMA: [number, number, number, number] = [51, 76, 101, 201];

describe("levelFor", () => {
  it("maps AQI to the asthma-tuned mask level", () => {
    expect(levelFor(40, ASTHMA)).toBe("none");
    expect(levelFor(60, ASTHMA)).toBe("carry");
    expect(levelFor(80, ASTHMA)).toBe("recommended");
    expect(levelFor(150, ASTHMA)).toBe("strong");
    expect(levelFor(250, ASTHMA)).toBe("indoors");
    expect(levelFor(null, ASTHMA)).toBe("none");
  });
});

describe("severity + describe", () => {
  it("orders levels and defaults unknowns to 0", () => {
    expect(severity("none")).toBe(0);
    expect(severity("indoors")).toBe(4);
    expect(severity("bogus")).toBe(0);
  });

  it("describes mask type per level", () => {
    expect(describeLevel("carry").mask_type).toBe("N95 optional");
    expect(describeLevel("recommended").mask_type).toBe("Well-fitted N95 or KN95");
    expect(allLevels()).toHaveLength(5);
  });
});

describe("recommend", () => {
  it("builds a full recommendation payload", () => {
    const reco = recommend(80, ASTHMA, { dominant: "pm2_5", trend: "worsening" });
    expect(reco.level).toBe("recommended");
    expect(reco.aqi).toBe(80);
    expect(reco.dominant).toBe("pm2_5");
    expect(reco.trend).toBe("worsening");
    expect(reco.disclaimer).toContain("not medical advice");
  });
});
