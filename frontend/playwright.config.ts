import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.pw.ts",
  fullyParallel: true,
  workers: 2,
  use: { baseURL: "http://127.0.0.1:5176", browserName: "chromium" },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 5176 --strictPort",
    url: "http://127.0.0.1:5176",
    env: { VITE_GOOGLE_CLIENT_ID: "layout-test.apps.googleusercontent.com" },
  },
});
