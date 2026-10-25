import { defineConfig, devices } from "@playwright/test";
import { existsSync } from "node:fs";
import path from "node:path";
const database = path.join(process.cwd(), ".local/e2e.sqlite");
export default defineConfig({
  testDir: "./tests/browser", fullyParallel: false, workers: 1,
  use: { baseURL: "http://127.0.0.1:3100", ...devices["Desktop Chrome"],
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || (existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : undefined) },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "python tests/seed_e2e.py && npm run dev -- --port 3100",
    env: { OFIR_DB_PATH: database, OFIR_STORAGE: "sqlite", LOCAL_DEV_MODE: "1", APP_URL: "http://127.0.0.1:3100", NEXT_TELEMETRY_DISABLED: "1", OFIR_E2E: "1" },
    url: "http://127.0.0.1:3100", reuseExistingServer: false, timeout: 60000,
  },
});
