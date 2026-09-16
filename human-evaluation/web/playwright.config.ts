import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e", outputDir: "../test-results", workers: 1,
  use: { baseURL: "http://127.0.0.1:8811", viewport: { width: 1440, height: 1100 },
    launchOptions: { executablePath: process.env.EVAL_BROWSER_EXECUTABLE } },
  webServer: { command: "../.venv/bin/python -m uvicorn browser_server:app --app-dir ../tests --host 127.0.0.1 --port 8811",
    url: "http://127.0.0.1:8811/api/health", reuseExistingServer: false },
});
