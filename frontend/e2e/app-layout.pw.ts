import { expect, test, type Page } from "@playwright/test";

const user = {
  id: "user-1",
  email: "admin@gmail.com",
  display_name: "Nguyễn Khánh",
  avatar_url: null,
  is_verified: true,
  is_admin: true,
};

async function mockAuthenticatedApi(page: Page) {
  await page.addInitScript((currentUser) => {
    localStorage.setItem("vta_session", JSON.stringify({
      access_token: "access",
      refresh_token: "refresh",
      user: currentUser,
    }));
  }, user);
  await page.route("http://localhost:8000/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith("/admin/conversations") || path.endsWith("/admin/agent-runs")) return route.fulfill({ json: { items: [], total: 0, limit: 20, offset: 0 } });
    if (path.endsWith("/admin/knowledge")) return route.fulfill({ json: { documents: 84, active_documents: 84, entity_candidates: 1843, last_import_at: null, collection: "travel_chunks", qdrant_status: "green", points: 287, vector_size: 1024, distance: "Cosine" } });
    if (path.endsWith("/users/me")) return route.fulfill({ json: user });
    if (path.endsWith("/conversations")) return route.fulfill({ json: [
      { id: "chat-1", title: "Lịch trình Đà Lạt 3 ngày", created_at: "2026-10-11T01:00:00Z", updated_at: "2026-10-11T01:30:00Z", last_message_at: "2026-10-11T01:30:00Z", is_archived: false },
      { id: "chat-2", title: "Phú Quốc hay Nha Trang?", created_at: "2026-10-10T01:00:00Z", updated_at: "2026-10-10T01:30:00Z", last_message_at: "2026-10-10T01:30:00Z", is_archived: false },
    ] });
    if (path.endsWith("/admin/overview")) return route.fulfill({ json: { total_users: 128, active_users: 119, total_conversations: 246, total_runs: 412, successful_runs: 397, degraded_runs: 9, failed_runs: 6, requests_today: 32, average_latency_ms: 3200, p50_latency_ms: 2800, p95_latency_ms: 6100, tool_usage: { search_travel_knowledge: 205, weather: 48, routing: 31 } } });
    if (path.endsWith("/admin/users")) return route.fulfill({ json: { items: [{ ...user, is_active: true, created_at: "2026-10-03T01:00:00Z", conversation_count: 12, run_count: 24, providers: ["google", "local"], last_login_at: "2026-10-11T01:00:00Z" }], total: 128, limit: 20, offset: 0 } });
    return route.fulfill({ status: 404, json: { detail: "Not found" } });
  });
}

for (const viewport of [{ name: "desktop", width: 1440, height: 900 }, { name: "phone", width: 390, height: 844 }]) {
  test(`client shell fits ${viewport.name}`, async ({ page }, info) => {
    await mockAuthenticatedApi(page);
    await page.setViewportSize(viewport);
    await page.goto("/");
    await expect(page.getByText("Bạn muốn khám phá đâu hôm nay?")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    await page.screenshot({ path: info.outputPath("client.png"), fullPage: true });
  });

  test(`admin overview fits ${viewport.name}`, async ({ page }, info) => {
    await mockAuthenticatedApi(page);
    await page.setViewportSize(viewport);
    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: "Người dùng", exact: true })).toBeVisible();
    await expect(page.getByText("128")).toBeVisible();
    await expect(page.getByRole("button", { name: "moon" })).toBeVisible();
    await expect(page.locator(".ant-spin-container")).not.toHaveClass(/ant-spin-blur/);
    await page.waitForTimeout(400);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    await page.screenshot({ path: info.outputPath("admin.png"), fullPage: true });
  });
}

test("admin navigation, language and theme remain usable on mobile", async ({ page }) => {
  await mockAuthenticatedApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/admin");
  await page.getByRole("button", { name: "moon" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByText("EN", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "Users", exact: true })).toBeVisible();
  for (const name of ["Conversations", "AI Runs", "Knowledge Base"]) {
    await page.getByRole("navigation").getByRole("button", { name, exact: true }).click();
    await expect(page.getByRole("heading", { name, exact: true }).first()).toBeVisible();
    await expect(page.locator(".ant-spin-container")).not.toHaveClass(/ant-spin-blur/);
    await expect(page.getByRole("alert")).toHaveCount(0);
  }
  await expect(page.getByText("travel_chunks").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
