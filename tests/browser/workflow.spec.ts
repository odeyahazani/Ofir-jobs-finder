import { test, expect } from "@playwright/test";

test("only verified eligible jobs are recommended; all source states remain visible", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /היי אופיר/ })).toBeVisible();
  await expect(page.locator(".job-card")).toHaveCount(1);
  await expect(page.getByText("אומתה במקור", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "כל המשרות", exact: true }).click();
  await expect(page.locator(".job-card")).toHaveCount(3);
  await page.getByRole("button", { name: /חברות במעקב/ }).click();
  await expect(page.locator(".company-row")).toHaveCount(138);
  await page.getByRole("textbox", { name: "חיפוש חברות" }).fill("ForSight");
  await expect(page.locator(".company-row")).toHaveCount(1);
  await expect(page.getByText("טרם נבדק", { exact: true })).toBeVisible();
});

test("feedback, familiarity, application state and notes persist after reload", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "לפרטים ולסימון" }).click();
  await page.getByRole("combobox", { name: "מידת ההתאמה בעיניי" }).selectOption("yes");
  await expect(page.getByRole("combobox", { name: "מידת ההתאמה בעיניי" })).toBeEnabled();
  await page.getByRole("combobox", { name: "מצב מועמדות" }).selectOption("applied");
  await expect(page.getByRole("combobox", { name: "מצב מועמדות" })).toBeEnabled();
  await page.getByRole("checkbox", { name: "המשרה כבר מוכרת לי" }).check();
  await expect(page.getByRole("checkbox")).toBeEnabled();
  await page.getByRole("textbox", { name: "הערה אישית" }).fill("לחזור למגייסת בשבוע הבא");
  await page.getByRole("button", { name: "שמירת הערה" }).click();
  await expect(page.getByRole("button", { name: "שמירת הערה" })).toBeEnabled();
  await page.reload();
  await page.getByRole("button", { name: "כל המשרות", exact: true }).click();
  await page.getByRole("button", { name: "TEST ONLY · Junior Integration Engineer 0", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "מידת ההתאמה בעיניי" })).toHaveValue("yes");
  await expect(page.getByRole("combobox", { name: "מצב מועמדות" })).toHaveValue("applied");
  await expect(page.getByRole("checkbox")).toBeChecked();
  await expect(page.getByRole("textbox", { name: "הערה אישית" })).toHaveValue("לחזור למגייסת בשבוע הבא");
  await page.getByRole("button", { name: "סגירה" }).click();
  await page.getByRole("button", { name: "המועמדויות שלי", exact: true }).click();
  await expect(page.locator(".job-card")).toHaveCount(1);
});

test("mutation rejects cross-origin requests, invalid fields and missing jobs", async ({ page, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "כל המשרות", exact: true }).click();
  const missing = "000000000000000000000000";
  const denied = await request.patch(`/api/jobs/${missing}`, { headers: { Origin: "https://attacker.example" }, data: { fit: "yes" } });
  expect(denied.status()).toBe(403);
  const invalid = await request.patch(`/api/jobs/${missing}`, { headers: { Origin: "http://127.0.0.1:3100" }, data: { score: 100 } });
  expect(invalid.status()).toBe(400);
  const absent = await request.patch(`/api/jobs/${missing}`, { headers: { Origin: "http://127.0.0.1:3100" }, data: { fit: "yes" } });
  expect(absent.status()).toBe(404);
  const forwarded = await request.get("/", { headers: { "x-forwarded-host": "public.example" }, maxRedirects: 0 });
  expect(forwarded.status()).toBe(307);
});

test("mobile layout has no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.getByRole("button", { name: /חברות במעקב/ }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
