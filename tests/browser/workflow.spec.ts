import { test, expect } from "@playwright/test";

test("only verified eligible jobs are recommended; all source states remain visible", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "הזדמנויות", exact: true })).toBeVisible();
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
  await page.getByRole("tab", { name: "המעקב שלי" }).click();
  await page.getByRole("combobox", { name: "מידת ההתאמה בעיניי" }).selectOption("yes");
  await expect(page.getByRole("combobox", { name: "מידת ההתאמה בעיניי" })).toBeEnabled();
  await page.getByRole("combobox", { name: "מצב מועמדות" }).selectOption("applied");
  await expect(page.getByRole("combobox", { name: "מצב מועמדות" })).toBeEnabled();
  await page.getByRole("checkbox", { name: "המשרה כבר מוכרת לי" }).check();
  await expect(page.getByRole("checkbox")).toBeEnabled();
  await page.getByRole("textbox", { name: "הערה אישית" }).fill("לחזור למגייסת בשבוע הבא");
  await page.getByRole("button", { name: "שמירת הערה" }).click();
  await expect(page.getByRole("dialog").getByRole("status")).toHaveText("השינויים נשמרו");
  await page.reload();
  await page.getByRole("button", { name: "כל המשרות", exact: true }).click();
  await page.getByRole("button", { name: "TEST ONLY · Junior Integration Engineer 0", exact: true }).click();
  await page.getByRole("tab", { name: "המעקב שלי" }).click();
  await expect(page.getByRole("combobox", { name: "מידת ההתאמה בעיניי" })).toHaveValue("yes");
  await expect(page.getByRole("combobox", { name: "מצב מועמדות" })).toHaveValue("applied");
  await expect(page.getByRole("checkbox")).toBeChecked();
  await expect(page.getByRole("textbox", { name: "הערה אישית" })).toHaveValue("לחזור למגייסת בשבוע הבא");
  await page.getByRole("button", { name: "סגירה" }).click();
  await page.getByRole("button", { name: /המועמדויות שלי/ }).click();
  await expect(page.locator(".application-table tbody tr")).toHaveCount(1);
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
  await page.getByRole("tab", { name: "המעקב שלי" }).click();
  const checkbox = page.getByRole("checkbox", { name: "המשרה כבר מוכרת לי" });
  const initial = await checkbox.isChecked();
  await page.route("**/api/jobs/*", route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "בדיקת כשל שמירה" }) }));
  await checkbox.click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("בדיקת כשל שמירה");
  if (initial) await expect(checkbox).toBeChecked(); else await expect(checkbox).not.toBeChecked();
});

test("quick actions persist, recover after failure, and retain application history", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "כל המשרות", exact: true }).click();
  const card = page.locator(".job-card").filter({ has: page.getByRole("button", { name: "TEST ONLY · Junior Integration Engineer 1", exact: true }) });
  await card.getByRole("button", { name: "שמירה להמשך", exact: true }).click();
  await expect(card.getByRole("button", { name: "שמורה", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(card.getByRole("button", { name: "שמורה", exact: true })).toBeEnabled();
  await page.reload();
  await page.getByRole("button", { name: "כל המשרות", exact: true }).click();
  await expect(card.getByRole("button", { name: "שמורה", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.route("**/api/jobs/*", route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "שמירה נכשלה בבדיקה" }) }));
  await card.getByRole("button", { name: "מוכרת לי", exact: true }).click();
  await expect(page.locator("main").getByRole("alert")).toContainText("שמירה נכשלה בבדיקה");
  await expect(card.getByRole("button", { name: "מוכרת לי", exact: true })).toHaveAttribute("aria-pressed", "false");
  await page.unroute("**/api/jobs/*");
  await card.getByRole("button", { name: "מוכרת לי", exact: true }).click();
  await expect(card.getByRole("button", { name: "מוכרת לי", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(card.getByRole("button", { name: "מוכרת לי", exact: true })).toBeEnabled();
  await card.getByRole("button", { name: "לפרטים ולסימון" }).click();
  await expect(page.getByRole("dialog").getByRole("link", { name: "בדיקת המשרה במקור" })).toHaveAttribute("href", "https://example.com/test-only/1");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(card.getByRole("button", { name: "לפרטים ולסימון" })).toBeFocused();
});

test("redesign remains usable at all target sizes with real controls and screenshots", async ({ page }) => {
  const fs = await import("node:fs/promises");
  const folder = "/tmp/artifacts/ofir-ux-refresh";
  await fs.mkdir(folder, { recursive: true });
  for (const [width,height] of [[1440,900],[1280,800],[1024,768],[768,1024],[390,844]]) {
    await page.setViewportSize({width,height});
    await page.goto("/");
    await page.getByRole("button", { name: "כל המשרות", exact: true }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    const first = page.locator(".job-card").first();
    await expect(first).toBeVisible();
    if (width >= 1024) expect((await first.boundingBox())!.y).toBeLessThan(450);
    await page.screenshot({ path: `${folder}/opportunities-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "TEST ONLY · Junior Integration Engineer 0", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.locator(".detail-panel")).toHaveCSS("opacity", "1");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    if (width === 390 || width === 1440) await page.screenshot({ path: `${folder}/details-${width}.png` });
    await page.keyboard.press("Escape");
    for (const [name,slug] of [["חברות במעקב","companies"],["המועמדויות שלי","applications"],["ייבוא ממצאים","import"]]) {
      await page.getByRole("button", { name: new RegExp(name) }).click();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
      if (width === 390 || width === 1440) await page.screenshot({ path: `${folder}/${slug}-${width}.png`, fullPage: true });
    }
  }
});

test("outside click closes native dialog, inside clicks and drags do not, and focus returns", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "כל המשרות", exact: true }).click();
  const opener = page.getByRole("button", { name: "TEST ONLY · Junior Integration Engineer 0", exact: true });
  await opener.click();
  const panel = page.locator(".detail-panel");
  await panel.locator("h2").click();
  await expect(page.getByRole("dialog")).toBeVisible();
  const box = (await panel.boundingBox())!;
  const outside = { x: box.x + box.width + 50, y: 160 };
  await page.mouse.move(box.x + 40, box.y + 120);
  await page.mouse.down();
  await page.mouse.move(outside.x, outside.y);
  await page.mouse.up();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.mouse.click(outside.x, outside.y);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(opener).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe("hidden");
});

test("notes remain drafts across dismissal, tab keyboard navigation and job navigation work", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "כל המשרות", exact: true }).click();
  const opener = page.getByRole("button", { name: "TEST ONLY · Junior Integration Engineer 0", exact: true });
  await opener.click();
  await page.getByRole("tab", { name: "תיאור המשרה", exact: true }).focus();
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByRole("tab", { name: "התאמה ופערים", exact: true })).toBeFocused();
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "המעקב שלי", exact: true })).toBeFocused();
  await page.getByRole("textbox", { name: "הערה אישית" }).fill("טיוטה שלא נשמרה בבדיקה");
  await page.keyboard.press("Escape");
  await opener.click();
  await page.getByRole("tab", { name: "המעקב שלי" }).click();
  await expect(page.getByRole("textbox", { name: "הערה אישית" })).toHaveValue("טיוטה שלא נשמרה בבדיקה");
  await page.getByRole("button", { name: "המשרה הבאה" }).click();
  await expect(page.getByRole("dialog").getByRole("heading", { level: 2 })).not.toHaveText("TEST ONLY · Junior Integration Engineer 0");
  await page.getByRole("button", { name: "המשרה הקודמת" }).click();
  await expect(page.getByRole("textbox", { name: "הערה אישית" })).toHaveValue("טיוטה שלא נשמרה בבדיקה");
  await page.keyboard.press("Escape");
});

test("long descriptions scroll independently with visible actions and keyboard focus contained", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "כל המשרות", exact: true }).click();
  await page.getByRole("button", { name: "TEST ONLY · Junior Integration Engineer 0", exact: true }).click();
  const scroll = page.locator(".detail-scroll");
  expect(await scroll.evaluate(element => element.scrollHeight > element.clientHeight)).toBeTruthy();
  await scroll.evaluate(element => { element.scrollTop = element.scrollHeight; });
  await expect(page.getByRole("dialog").getByRole("link", { name: "למשרה באתר החברה" })).toBeInViewport();
  await expect(page.getByRole("button", { name: "סגירה", exact: true })).toBeInViewport();
  await page.getByRole("button", { name: "סגירה", exact: true }).focus();
  for (let index = 0; index < 14; index++) {
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => !!document.activeElement?.closest("dialog"))).toBeTruthy();
  }
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});


test("profile categories, requirement gaps and project evidence stay separate from source verification", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "שוות בדיקה", exact: true }).click();
  const review = page.locator(".job-card");
  await expect(review).toHaveCount(1);
  await expect(review.getByText("שווה בדיקה", { exact: true })).toBeVisible();
  await expect(review.getByText("טרם אומתה", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "פערים בדרישות", exact: true }).click();
  await expect(page.locator(".job-card")).toHaveCount(1);
  await expect(page.locator(".job-card").getByText(/דרישת ניסיון של 3/)).toBeVisible();
  await page.getByRole("button", { name: "כל המשרות", exact: true }).click();
  await page.getByRole("button", { name: "TEST ONLY · Junior Integration Engineer 0", exact: true }).click();
  await page.getByRole("tab", { name: "התאמה ופערים", exact: true }).click();
  await expect(page.getByRole("dialog").getByText(/לא מתועד ניסיון הנדסי תעשייתי/)).toBeVisible();
  const evidence = page.locator(".evidence-item").filter({ hasText: "MATLAB לניתוח ולמידול" });
  await evidence.locator("summary").click();
  await expect(evidence.getByText(/פרויקט גמר SFDI/)).toBeVisible();
  await expect(evidence.getByText(/שחזור CT/)).toBeVisible();
  await expect(evidence.locator("blockquote")).toContainText("MATLAB");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: "/tmp/artifacts/ofir-ux-refresh/matching-evidence-mobile.png" });
});

test("rows pending recalculation show an explicit legacy state through the deployment transition", async ({ page }) => {
  const { DatabaseSync } = await import("node:sqlite");
  const db = new DatabaseSync(".local/e2e.sqlite");
  const original = db.prepare("SELECT id,match_category,match_version,match_details FROM jobs WHERE source_id='test-only-0'").get()!;
  try {
    db.prepare("UPDATE jobs SET match_category=NULL,match_version=NULL,match_details=NULL WHERE id=?").run(String(original.id));
    await page.goto("/");
    await expect(page.getByText(/1 משרות טרם הותאמו לפרופיל המפורט/)).toBeVisible();
    await page.getByRole("button", { name: "כל המשרות", exact: true }).click();
    const card = page.locator(".job-card").filter({ hasText: "TEST ONLY · Junior Integration Engineer 0" });
    await expect(card.getByText("טרם הותאמה לפרופיל החדש", { exact: true })).toBeVisible();
    await card.getByRole("button", { name: "לפרטים ולסימון" }).click();
    await page.getByRole("tab", { name: "התאמה ופערים", exact: true }).click();
    await expect(page.getByText(/הערכה קודמת/)).toBeVisible();
  } finally {
    db.prepare("UPDATE jobs SET match_category=?,match_version=?,match_details=? WHERE id=?").run(String(original.match_category), String(original.match_version), String(original.match_details), String(original.id));
    db.close();
  }
});
