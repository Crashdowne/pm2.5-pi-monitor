// Minimal D1Database-compatible adapter over Node's built-in node:sqlite, for tests.
// The Worker handlers only use prepare().bind().run()/.first()/.all() and batch(), so a
// thin shim over the same SQLite engine family that backs D1 exercises the real SQL
// (multi-row upserts, INSERT..SELECT rollups, aggregates) without workerd.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

class Bound {
  constructor(
    private db: DatabaseSync,
    private sql: string,
    private params: unknown[],
  ) {}
  private norm() {
    return this.params.map((p) => (p === undefined ? null : p));
  }
  async run() {
    const info = this.db.prepare(this.sql).run(...this.norm());
    return { success: true, meta: { changes: Number(info.changes) } };
  }
  async all<T = unknown>() {
    const results = this.db.prepare(this.sql).all(...this.norm()) as T[];
    return { results, success: true, meta: {} };
  }
  async first<T = unknown>(col?: string): Promise<T | null> {
    const row = this.db.prepare(this.sql).get(...this.norm()) as Record<string, unknown> | undefined;
    if (row == null) return null;
    return (col ? row[col] : row) as T;
  }
  async raw<T = unknown>(): Promise<T[]> {
    const rows = this.db.prepare(this.sql).all(...this.norm()) as Record<string, unknown>[];
    return rows.map((r) => Object.values(r)) as T[];
  }
}

class Prepared {
  constructor(
    private db: DatabaseSync,
    private sql: string,
  ) {}
  bind(...params: unknown[]) {
    return new Bound(this.db, this.sql, params);
  }
  run() {
    return new Bound(this.db, this.sql, []).run();
  }
  all<T = unknown>() {
    return new Bound(this.db, this.sql, []).all<T>();
  }
  first<T = unknown>(col?: string) {
    return new Bound(this.db, this.sql, []).first<T>(col);
  }
}

export interface TestDB {
  prepare(sql: string): Prepared;
  batch(stmts: Bound[]): Promise<unknown[]>;
  exec(sql: string): Promise<void>;
  _db: DatabaseSync;
}

export function createTestDB(): TestDB {
  const db = new DatabaseSync(":memory:");
  db.exec(readFileSync(join(here, "..", "migrations", "0001_init.sql"), "utf8"));
  return {
    _db: db,
    prepare(sql: string) {
      return new Prepared(db, sql);
    },
    async batch(stmts: Bound[]) {
      db.exec("BEGIN");
      try {
        const out: unknown[] = [];
        for (const s of stmts) out.push(await s.run());
        db.exec("COMMIT");
        return out;
      } catch (e) {
        db.exec("ROLLBACK");
        throw e;
      }
    },
    async exec(sql: string) {
      db.exec(sql);
    },
  };
}
