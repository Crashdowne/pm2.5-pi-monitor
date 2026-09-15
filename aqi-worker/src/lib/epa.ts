// US EPA AQI for PM2.5/PM10 — TypeScript port of src/pm25/aqi.py.
// MUST stay numerically identical to the Python source (verified by probes/parity.ts).

export type Pollutant = "pm2_5" | "pm10";

// (C_low, C_high, I_low, I_high) — PM2.5 breakpoints effective May 2024.
const PM25: [number, number, number, number][] = [
  [0.0, 9.0, 0, 50],
  [9.1, 35.4, 51, 100],
  [35.5, 55.4, 101, 150],
  [55.5, 125.4, 151, 200],
  [125.5, 225.4, 201, 300],
  [225.5, 500.4, 301, 500],
];
const PM10: [number, number, number, number][] = [
  [0, 54, 0, 50],
  [55, 154, 51, 100],
  [155, 254, 101, 150],
  [255, 354, 151, 200],
  [355, 424, 201, 300],
  [425, 604, 301, 500],
];

// (I_high, label, color)
const CATEGORIES: [number, string, string][] = [
  [50, "Good", "#00e400"],
  [100, "Moderate", "#ffff00"],
  [150, "Unhealthy for Sensitive Groups", "#ff7e00"],
  [200, "Unhealthy", "#ff0000"],
  [300, "Very Unhealthy", "#8f3f97"],
  [500, "Hazardous", "#7e0023"],
];

// Python's round(): round-half-to-even ("banker's rounding") on the TRUE value of the
// double, matching CPython. A scaled-integer approach (x * 10**nd) fails here because
// the multiply's float noise (~1e-14 at AQI magnitudes) exceeds the gap between a real
// tie and a near-tie, so ties get misclassified. Instead we read the true decimal
// expansion via toFixed() and round the digit string. This port only uses ndigits >= 0.
export function pyRound(x: number, ndigits = 0): number {
  if (!Number.isFinite(x)) return x;
  if (x === 0) return 0;
  const neg = x < 0;
  const nd = ndigits < 0 ? 0 : ndigits;
  const s = Math.abs(x).toFixed(nd + 25); // enough places to break ties correctly
  const dot = s.indexOf(".");
  const intPart = dot < 0 ? s : s.slice(0, dot);
  const fracPart = dot < 0 ? "" : s.slice(dot + 1);
  const digits = intPart + fracPart.slice(0, nd); // integer value scaled by 10**nd
  const rest = fracPart.slice(nd);
  let roundUp = false;
  if (rest.length > 0) {
    const first = rest.charCodeAt(0) - 48;
    if (first > 5) {
      roundUp = true;
    } else if (first === 5) {
      if (/[1-9]/.test(rest.slice(1))) {
        roundUp = true; // more nonzero digits follow -> above the midpoint
      } else {
        const lastKept = digits.length ? digits.charCodeAt(digits.length - 1) - 48 : 0;
        roundUp = lastKept % 2 === 1; // exact tie -> round to even
      }
    }
  }
  let n = BigInt(digits.length ? digits : "0");
  if (roundUp) n += 1n;
  const result = Number(n) / 10 ** nd;
  return neg ? -result : result;
}

function truncate(c: number, pollutant: Pollutant): number {
  // EPA truncation: PM2.5 to 0.1 ug/m3, PM10 to whole ug/m3, before lookup.
  if (pollutant === "pm2_5") return Math.floor(c * 10) / 10;
  return Math.floor(c);
}

export function aqi(pollutant: Pollutant, c: number | null): number | null {
  if (c === null || c === undefined) return null;
  c = truncate(Math.max(0.0, c), pollutant);
  const table = pollutant === "pm2_5" ? PM25 : PM10;
  for (const [cLow, cHigh, iLow, iHigh] of table) {
    if (c <= cHigh) {
      const cc = Math.max(c, cLow);
      return pyRound(((iHigh - iLow) / (cHigh - cLow)) * (cc - cLow) + iLow);
    }
  }
  return 500; // above the highest breakpoint
}

export function category(a: number | null): { label: string; color: string } {
  if (a === null || a === undefined) return { label: "Unknown", color: "#9ca3af" };
  for (const [iHigh, label, color] of CATEGORIES) {
    if (a <= iHigh) return { label, color };
  }
  return { label: "Hazardous", color: "#7e0023" };
}

// EPA NowCast from recent hourly concentrations (oldest first, most-recent last).
export function nowcast(hourlyValues: (number | null)[]): number | null {
  const recent: number[] = [];
  for (let i = hourlyValues.length - 1; i >= 0 && recent.length < 12; i--) {
    const v = hourlyValues[i];
    if (v !== null && v !== undefined) recent.push(v);
  }
  if (recent.length < 2) return null;
  const cMin = Math.min(...recent);
  const cMax = Math.max(...recent);
  if (cMax === 0) return 0.0;
  const weight = Math.max(0.5, 1.0 - (cMax - cMin) / cMax);
  let num = 0;
  let den = 0;
  for (let i = 0; i < recent.length; i++) {
    num += recent[i] * weight ** i;
    den += weight ** i;
  }
  return den ? num / den : null;
}

// EPA/Barkjohn US-wide humidity correction. Input is the CF=1 PM2.5 channel; rh is % RH.
export function correctPm25(pmCf1: number | null, rh: number | null): number | null {
  if (pmCf1 === null || pmCf1 === undefined || rh === null || rh === undefined) return null;
  return pyRound(Math.max(0.0, 0.524 * pmCf1 - 0.0862 * rh + 5.75), 1);
}
