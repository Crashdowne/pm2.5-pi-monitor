// Seed a TestDB warehouse (raw readings + maintained rollups) for read/alert tests.
// Three sensors mirror aqi-site's fixtures: full env + correction, no-env, wildfire-high.
import { pyRound } from "../src/lib/epa.ts";
import { buildRollupUpserts, RAW_COLS } from "../src/lib/ingest.ts";
import type { TestDB } from "./d1-adapter.ts";

const COLS = ["sensor_id", "ts", ...RAW_COLS] as const;

type SeedRow = Record<string, number | string | null>;

function row(sensorId: string, ts: number, pm2_5: number, opts: { corr?: boolean; env?: boolean } = {}): SeedRow {
  const corr = opts.corr ?? true;
  const hasEnv = opts.env ?? true;
  const rh = hasEnv ? 55.0 : null;
  const temp = hasEnv ? 20.0 : null;
  return {
    sensor_id: sensorId,
    ts,
    pm1_0: pyRound(pm2_5 * 0.8, 1),
    pm2_5: pyRound(pm2_5, 1),
    pm10: pyRound(pm2_5 * 1.4, 1),
    pm2_5_corr: corr ? pyRound(Math.max(0.0, 0.524 * pm2_5 - 0.0862 * (rh ?? 0) + 5.75), 1) : null,
    n0_3: 100, n0_5: 50, n1_0: 20, n2_5: 5, n5_0: 2, n10: 1,
    rh, temp,
  };
}

/** Seed a warehouse into `db`. Returns the `now` timestamp used. */
export async function seedWarehouse(db: TestDB, now = Math.floor(Date.now() / 1000)): Promise<number> {
  const rows: SeedRow[] = [];
  // backyard: 48h @ 15 min, moderate diurnal swing, full env + correction.
  for (let i = 0; i < 192; i++) {
    const ts = now - i * 900;
    const pm = 25 + 20 * Math.sin(i / 8.0) + 10 * Math.sin(i / 40.0);
    rows.push(row("backyard", ts, Math.max(2.0, pm)));
  }
  // rooftop: 30 days @ hourly, low values, NO env/correction (SHT31 disabled).
  for (let i = 0; i < 720; i++) {
    const ts = now - i * 3600;
    const pm = 12 + 8 * Math.sin(i / 12.0);
    rows.push(row("rooftop", ts, Math.max(2.0, pm), { corr: false, env: false }));
  }
  // smoky: 12h @ 15 min, very high (wildfire-like).
  for (let i = 0; i < 48; i++) {
    const ts = now - i * 900;
    rows.push(row("smoky", ts, 260.0));
  }

  const placeholders = new Array(COLS.length).fill("?").join(",");
  const insert = `INSERT INTO readings_raw (${COLS.join(",")}) VALUES (${placeholders})`;
  for (let i = 0; i < rows.length; i += 200) {
    await db.batch(rows.slice(i, i + 200).map((r) => db.prepare(insert).bind(...COLS.map((c) => r[c]))));
  }

  const devices: [string, number][] = [["backyard", 900], ["rooftop", 3600], ["smoky", 900]];
  for (const [sid, period] of devices) {
    const tss = rows.filter((r) => r.sensor_id === sid).map((r) => r.ts as number);
    const minTs = Math.min(...tss);
    const maxTs = Math.max(...tss);
    const rollups = buildRollupUpserts(sid, minTs, maxTs);
    await db.batch(rollups.map((s) => db.prepare(s.sql).bind(...s.params)));
    await db
      .prepare(
        "INSERT INTO devices (sensor_id, sample_period_s, last_ingest_ts, last_reading_ts) VALUES (?,?,?,?)",
      )
      .bind(sid, period, now, maxTs)
      .run();
  }
  return now;
}
