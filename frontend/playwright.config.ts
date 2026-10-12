import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.pw.ts",
  fullyParallel: true,
  workers: 2,
  reporter: [["list"], ["html", { open: "never" }]],
  retries: process.env.CI ? 1 : 0,
  forbidOnly: Boolean(process.env.CI),
  use: { baseURL: "http://127.0.0.1:5176", browserName: "chromium", trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: [{
    command: "npm run dev -- --host 127.0.0.1 --port 5176 --strictPort",
    url: "http://127.0.0.1:5176",
    env: { VITE_GOOGLE_CLIENT_ID: "layout-test.apps.googleusercontent.com", VITE_API_BASE_URL: process.env.E2E_API_URL || "http://localhost:8000/api/v1" },
  }, ...(process.env.E2E_MOCK_BACKEND === "1" ? [{
    command: `"${process.env.E2E_PYTHON || "python"}" -m uvicorn tests.e2e_app:app --host 127.0.0.1 --port 8010`,
    cwd: "../backend",
    url: "http://127.0.0.1:8010/health",
    env: { CORS_ORIGINS: "http://127.0.0.1:5176", REDIS_ENABLED: "false", RATE_LIMIT_ENABLED: "false", GEMINI_API_KEY: "", TAVILY_API_KEY: "" },
  }] : [])],
});
