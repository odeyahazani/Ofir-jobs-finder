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
  await expect(page.getByRole("combobox", { name: "מיקום המשרה" })).toHaveValue("israel");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.getByRole("button", { name: /חברות במעקב/ }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test("location defaults to Israel and keeps foreign and unclear records behind explicit filters", async ({ page }) => {
  await page.goto("/");
  const location = page.getByRole("combobox", { name: "מיקום המשרה" });
  await expect(location).toHaveValue("israel");
  await expect(page.getByRole("button", { name: "TEST ONLY · test-abroad", exact: true })).toHaveCount(0);
  await page.getByRole("textbox", { name: "חיפוש משרות" }).fill("NO MATCH LOCATION TEST");
  await page.getByRole("button", { name: "כל המשרות במיקום שנבחר", exact: true }).click();
  await expect(location).toHaveValue("israel");
  await expect(page.getByRole("textbox", { name: "חיפוש משרות" })).toHaveValue("");
  await expect(page.locator(".job-card")).toHaveCount(3);
  await location.selectOption("abroad");
  await expect(page.locator(".job-card")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "TEST ONLY · test-abroad", exact: true })).toBeVisible();
  await location.selectOption("unknown");
  await expect(page.locator(".job-card")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "TEST ONLY · test-unknown", exact: true })).toBeVisible();
  await location.selectOption("all");
  await expect(page.locator(".job-card")).toHaveCount(5);
  await page.getByRole("button", { name: "מומלצות", exact: true }).click();
  await expect(page.getByRole("button", { name: "TEST ONLY · test-abroad", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "TEST ONLY · test-unknown", exact: true })).toHaveCount(0);
  await page.reload();
  await expect(location).toHaveValue("israel");
});

test("findings import previews, deduplicates and preserves unverified status across reload", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "ייבוא ממצאים", exact: true }).click();
  const findings = JSON.stringify({ companies: [{ name: "TEST ONLY Imported Company", career_url: "https://www.comeet.com/jobs/test-only/AA.001", location: "Haifa", notes: "Ofir optics" }], jobs: [{ company: "TEST ONLY Imported Company", title: "TEST ONLY Imported Job", url: "https://example.com/imported-role?utm_source=chat", verified: true, score: 100 }] });
  async function importFile() {
    await page.getByRole("textbox", { name: "תוכן הממצאים" }).fill(findings);
    await page.getByRole("button", { name: "בדיקת הממצאים לפני ייבוא" }).click();
    await page.getByRole("button", { name: "אישור ייבוא למאגר" }).click();
  }
  await importFile();
  await expect(page.getByText(/נוספו 1 חברות ו־1 ממצאי משרות/)).toBeVisible();
  await expect(page.getByText("ממתינה לאימות", { exact: true })).toBeVisible();
  await importFile();
  await expect(page.getByText(/נוספו 0 חברות ו־0 ממצאי משרות/)).toBeVisible();
  await expect(page.locator(".discovery-row")).toHaveCount(1);
  await page.reload();
  await page.getByRole("button", { name: "ייבוא ממצאים", exact: true }).click();
  await expect(page.locator(".discovery-row")).toHaveCount(1);
  await page.getByRole("button", { name: /חברות במעקב/ }).click();
  await page.getByRole("textbox", { name: "חיפוש חברות" }).fill("TEST ONLY Imported Company");
  const monitor = page.getByRole("checkbox", { name: "מעקב אחר TEST ONLY Imported Company", exact: true });
  await expect(monitor).not.toBeChecked();
  await monitor.click(); await expect(monitor).toBeChecked();
  await page.reload();
  await page.getByRole("button", { name: /חברות במעקב/ }).click();
  await page.getByRole("textbox", { name: "חיפוש חברות" }).fill("TEST ONLY Imported Company");
  await expect(page.getByRole("checkbox", { name: "מעקב אחר TEST ONLY Imported Company", exact: true })).toBeChecked();
});

test("a rejected feedback save restores the previous checkbox state and reports failure", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "כל המשרות", exact: true }).click();
  await page.getByRole("button", { name: "TEST ONLY · Junior Integration Engineer 0", exact: true }).click();
  const checkbox = page.getByRole("checkbox", { name: "המשרה כבר מוכרת לי" });
  const initial = await checkbox.isChecked();
  await page.route("**/api/jobs/*", route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "בדיקת כשל שמירה" }) }));
  await checkbox.click();
  await expect(page.getByRole("dialog").getByRole("alert")).toHaveText("בדיקת כשל שמירה");
  if (initial) await expect(checkbox).toBeChecked(); else await expect(checkbox).not.toBeChecked();
});
