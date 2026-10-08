import { defineConfig } from "@playwright/test";
const runId = Date.now().toString();
export default defineConfig({
  testDir: "e2e",
  timeout: 60000,
  workers: 1,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:5173",
    viewport: { width: 1440, height: 1050 },
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command:
        "python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-access-log",
      cwd: "..",
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: false,
      env: {
        DATA_DIR: `.data/e2e/${runId}`,
        DATABASE_URL: `sqlite:///.data/e2e/${runId}/app.sqlite3`,
        BROWSER_HEADLESS: "true",
        ENABLE_MOCK_PORTAL: "true",
        OPENAI_API_KEY: "",
      },
      timeout: 120000,
    },
    {
      command:
        "python -m uvicorn mock_portal.main:app --host 127.0.0.1 --port 8001 --no-access-log",
      cwd: "..",
      url: "http://127.0.0.1:8001/mock/jobs/test",
      reuseExistingServer: false,
    },
    {
      command:
        "node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 5173 --strictPort",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
    },
  ],
});
