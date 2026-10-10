import { expect, test } from "@playwright/test";

const screens = [
  { name: "laptop", width: 1440, height: 900 },
  { name: "small-laptop", width: 1024, height: 600 },
  { name: "phone", width: 390, height: 844 },
  { name: "small-phone", width: 320, height: 568 },
  { name: "landscape-phone", width: 844, height: 390 },
  { name: "zoom-200-effective", width: 720, height: 450 },
  { name: "zoom-400-effective", width: 360, height: 225 },
  { name: "zoom-out-effective", width: 2560, height: 1440 },
];

test.beforeEach(async ({ page }) => {
  // Google OAuth itself is not exercised; this preserves the SDK button's fixed width.
  await page.route("https://accounts.google.com/gsi/client", route => route.fulfill({
    contentType: "application/javascript",
    body: `window.google={accounts:{id:{initialize(){},disableAutoSelect(){},renderButton(el,o){
      const b=document.createElement('button'); b.type='button'; b.textContent=o.type==='icon'?'G':'Tiếp tục với Google';
      b.style.width=o.width?o.width+'px':'44px'; b.style.height='44px';
      b.setAttribute('aria-label','Tiếp tục với Google'); el.appendChild(b);
    }}}};`,
  }));
});

for (const screen of screens) {
  for (const route of ["/login", "/register", "/forgot-password", "/reset-password#token=layout-test"]) {
    test(`${route} fits ${screen.name}`, async ({ page }, info) => {
      await page.setViewportSize({ width: screen.width, height: screen.height });
      await page.goto(route);
      await expect(page.locator("#auth-title")).toBeVisible();
      await expect(page.locator(".auth-page img")).toHaveCount(0);
      if (route === "/login" || route === "/register") await expect(page.getByRole("button", { name: "Tiếp tục với Google" })).toBeVisible();
      const dimensions = await page.evaluate(() => {
        const main = document.querySelector(".auth-page")!.getBoundingClientRect();
        const form = document.querySelector(".auth-panel")!.getBoundingClientRect();
        const elements = [...document.querySelectorAll(".auth-panel input, .auth-panel button, .auth-panel label, .auth-panel h1, .auth-panel p")];
        return { pageWidth: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth, x: main.x, width: main.width,
          overflowY: getComputedStyle(document.body).overflowY,
          overflow: elements.filter(el => { const r = el.getBoundingClientRect(); return r.left < form.left - 1 || r.right > form.right + 1; }).map(el => el.tagName) };
      });
      expect(dimensions.pageWidth).toBeLessThanOrEqual(dimensions.viewport + 1);
      expect(dimensions.x).toBe(0);
      expect(dimensions.width).toBe(dimensions.viewport);
      expect(dimensions.overflow).toEqual([]);
      expect(dimensions.overflowY).toBe("auto");
      await page.locator(".auth-submit").scrollIntoViewIfNeeded();
      await expect(page.locator(".auth-submit")).toBeInViewport();
      if (route === "/login" && ["laptop", "phone", "zoom-400-effective"].includes(screen.name)) {
        await page.screenshot({ path: info.outputPath("layout.png"), fullPage: true });
      }
    });
  }
}

test("Google button resizes when the viewport changes without reloading", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/login");
  const google = page.getByRole("button", { name: "Tiếp tục với Google" });
  await expect(google).toBeVisible();
  await page.setViewportSize({ width: 320, height: 568 });
  await expect.poll(async () => (await google.boundingBox())?.width ?? Infinity).toBeLessThanOrEqual(288);
  await page.setViewportSize({ width: 190, height: 400 });
  await expect(google).toHaveText("G");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(190);
});
