import { expect, test } from "@playwright/test";

test.skip(!process.env.E2E_API_URL, "Requires the isolated mock-LLM API fixture");

test.beforeEach(async ({ page, request }) => {
  const response = await request.post(`${process.env.E2E_API_URL}/auth/register`, {
    data: { email: `e2e-${crypto.randomUUID()}@gmail.com`, password: "E2ePassword123!" },
  });
  expect(response.status()).toBe(201);
  const session = await response.json();
  await page.addInitScript(value => localStorage.setItem("vta_session", JSON.stringify(value)), session);
  await page.goto("/");
});

test("real HTTP contract persists a question, streams progress and renders the answer", async ({ page }) => {
  const input = page.getByRole("textbox", { name: "Nội dung tin nhắn" });
  const submit = page.getByRole("button", { name: "Gửi", exact: true });
  await expect(submit).toBeDisabled();
  await input.fill("Lên lịch Huế 3 ngày");
  await submit.click();
  await expect(page.getByRole("status")).toBeVisible();
  await expect(submit).toBeDisabled();
  await expect(page.getByRole("heading", { name: "Lịch trình Huế", exact: true })).toBeVisible({ timeout: 15000 });
  await expect(input).toBeEnabled();
  await expect(page.getByRole("status")).toHaveCount(0);
  await expect.poll(() => page.locator(".conversation-view").evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)).toBeLessThan(120);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Lịch trình Huế", exact: true })).toBeVisible();
  await expect(page.locator(".user-message")).toHaveCount(1);
  await expect(page.locator(".assistant-message")).toHaveCount(1);
  const helpful = page.getByRole("button", { name: "Câu trả lời hữu ích" });
  await helpful.click();
  await expect(helpful).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(page.getByRole("button", { name: "Câu trả lời hữu ích" })).toHaveAttribute("aria-pressed", "true");
});

test("network failure restores the composer and the user can resend", async ({ page }) => {
  const input = page.getByRole("textbox", { name: "Nội dung tin nhắn" });
  const historyReloaded = page.waitForResponse(response =>
    response.request().method() === "GET" &&
    new URL(response.url()).pathname.endsWith("/messages") && response.ok());
  await page.route("**/messages/stream", route => route.abort("connectionreset"));
  await input.fill("Lên lịch Huế 3 ngày");
  await page.getByRole("button", { name: "Gửi", exact: true }).click();
  await historyReloaded;
  await expect(page.getByRole("alert").first()).toBeVisible();
  await expect(input).toBeEnabled();
  await page.unroute("**/messages/stream");
  await input.fill("Lên lịch Huế 3 ngày");
  await page.getByRole("button", { name: "Gửi", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Lịch trình Huế", exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole("alert")).toHaveCount(0);
});
