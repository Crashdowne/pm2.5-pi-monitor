import { defineConfig } from "vitest/config";

// Tests run in Node against a node:sqlite D1 shim (test/d1-adapter.ts) so the real
// analytics SQL and ingest path are exercised without workerd.
export default defineConfig({
  test: {
    environment: "node",
    include: ["test/**/*.test.ts"],
  },
});
