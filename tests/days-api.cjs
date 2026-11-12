const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const base = process.env.PANEL_URL || "http://127.0.0.1:5173";
const snapshot = "72b97835-0489-467c-8f8a-16864d14d62b";
const days = Array.from({ length: 7 }, (_, index) => ({
  day: new Date(Date.UTC(2026, 10, 5 - index)).toISOString().slice(0, 10),
  schema_version: 1,
  snapshot_id: snapshot,
  status: index === 0 ? "attention" : index === 1 ? "processing" : "partial",
  processing_scope: "layer1",
  raw_records: 100 + index,
  raw_document_bytes: null,
  chunk_size: index === 2 ? null : 20,
  expected_chunks: index === 2 ? null : 6,
  observed_chunks: 6,
  complete_chunks: 1,
  processing_chunks: index === 1 ? 1 : 0,
  attention_chunks: index === 0 ? 1 : 0,
  missing_chunks: index === 2 ? null : 0,
  chunk_coverage_percent: index === 2 ? null : 100,
  normalized_records: 100,
  candidate_records: 10,
  unassigned_records: { normalized_records: 0, candidate_records: 0 },
  warnings: [],
  created_at: "2026-11-12T11:00:00Z",
  updated_at: "2026-11-12T11:00:00Z",
}));
const chunks = Array.from({ length: 6 }, (_, index) => ({
  day: days[0].day,
  snapshot_id: snapshot,
  chunk_index: index,
  status: index === 0 ? "attention" : "partial",
  expected_raw_records: 20,
  normalized_records: 20,
  normalization_complete: true,
  candidate_records: 2,
  components: 0,
  representatives: 0,
  graph: null,
  updated_at: days[0].updated_at,
}));
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
    headless: true,
    args: ["--no-sandbox"],
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const liveResponse = await page.request.get(base + "/api/v1/days/");
  assert.equal(liveResponse.status(), 200);
  const liveDays = await liveResponse.json();
  await page.goto(base + "/#/days");
  if (liveDays.count === 0) {
    await page
      .getByText("روزی با این فیلتر پیدا نشد.", { exact: true })
      .waitFor();
    assert.equal(await page.locator(".day-row").count(), 0);
  } else {
    await page.locator(".day-row").first().waitFor();
  }
  assert.equal((await page.request.get(base + "/api/v1/days/")).status(), 200);
  assert(
    !(await page
      .locator("main")
      .innerText()
      .then((t) => t.includes("نسخهٔ ماک"))),
  );
  const calls = [];
  let failList = false,
    failChunks = false,
    slowDay = false,
    changedSnapshot = false;
  await page.route("**/api/v1/days/**", async (route) => {
    const url = new URL(route.request().url());
    calls.push(url.pathname + url.search);
    let results;
    if (url.pathname === "/api/v1/days/") {
      if (failList)
        return route.fulfill({
          status: 503,
          json: {
            code: "database_unavailable",
            detail: "internal secret must not show",
          },
        });
      results = days.filter(
        (d) =>
          (!url.searchParams.get("status") ||
            d.status === url.searchParams.get("status")) &&
          (!url.searchParams.get("q") ||
            d.day.startsWith(url.searchParams.get("q"))) &&
          (!url.searchParams.get("date_from") ||
            d.day >= url.searchParams.get("date_from")) &&
          (!url.searchParams.get("date_to") ||
            d.day <= url.searchParams.get("date_to")),
      );
      const offset = Number(url.searchParams.get("offset") || 0),
        limit = Number(url.searchParams.get("limit") || 10);
      return route.fulfill({
        json: {
          count: results.length,
          next: null,
          previous: null,
          results: results.slice(offset, offset + limit),
        },
      });
    }
    const match = /\/days\/([^/]+)\/(chunks\/)?$/.exec(url.pathname);
    const day = days.find((d) => d.day === match?.[1]);
    if (!day)
      return route.fulfill({
        status: 404,
        json: { code: "not_found", detail: "Day not found" },
      });
    if (match[2]) {
      if (failChunks)
        return route.fulfill({
          status: 503,
          json: { code: "database_unavailable" },
        });
      results = chunks
        .map((c) => ({ ...c, day: day.day }))
        .filter(
          (c) =>
            (!url.searchParams.has("chunk_index") ||
              c.chunk_index === Number(url.searchParams.get("chunk_index"))) &&
            (!url.searchParams.get("status") ||
              c.status === url.searchParams.get("status")),
        );
      const offset = Number(url.searchParams.get("offset") || 0),
        limit = Number(url.searchParams.get("limit") || 50);
      return route.fulfill({
        json: {
          day: day.day,
          snapshot_id: changedSnapshot ? "different-snapshot" : snapshot,
          chunks_are_processing_partitions: true,
          count: results.length,
          next: null,
          previous: null,
          results: results.slice(offset, offset + limit),
        },
      });
    }
    if (slowDay && day.day === days[1].day)
      await new Promise((r) => setTimeout(r, 500));
    return route.fulfill({ json: day });
  });
  await page.reload();
  await page.locator(".day-row").nth(4).waitFor();
  await page.locator(".chunks-table tbody tr").nth(3).waitFor();
  assert.equal(await page.locator(".day-row").count(), 5);
  assert(calls.some((u) => u.includes("limit=5") && u.includes("offset=0")));
  assert(
    calls.some((u) => u.includes("date_from=") && u.includes("limit=100")),
  );
  assert.equal(
    await page.locator(".chunks-table .duration-cell").first().innerText(),
    "—",
  );
  assert.equal(
    await page.locator(".chunk-progress span").first().innerText(),
    "—",
  );
  await page
    .getByRole("button", { name: "صفحهٔ بعدی چانک‌ها", exact: true })
    .click();
  await page.waitForFunction(() =>
    document.querySelector(".chunk-name")?.textContent.includes("۴"),
  );
  assert.equal(await page.locator(".chunk-name").count(), 2);
  assert(
    calls.some(
      (u) =>
        u.includes("/chunks/") &&
        u.includes("limit=4") &&
        u.includes("offset=4"),
    ),
  );
  await page
    .getByRole("textbox", { name: "جست‌وجوی چانک", exact: true })
    .fill("۵");
  await page.waitForFunction(
    () =>
      document.querySelectorAll(".chunk-name").length === 1 &&
      document.querySelector(".chunk-name")?.textContent.includes("۵"),
  );
  assert(calls.some((u) => u.includes("chunk_index=5")));
  await page
    .getByRole("textbox", { name: "جست‌وجوی چانک", exact: true })
    .fill("");
  await page.waitForFunction(
    () => document.querySelectorAll(".chunk-name").length === 4,
  );
  await page
    .getByRole("combobox", { name: "وضعیت چانک", exact: true })
    .selectOption("attention");
  await page.waitForFunction(
    () => document.querySelectorAll(".chunk-name").length === 1,
  );
  await page
    .getByRole("combobox", { name: "وضعیت چانک", exact: true })
    .selectOption("all");
  await page.waitForFunction(
    () => document.querySelectorAll(".chunk-name").length === 4,
  );
  await page.getByRole("tab", { name: "گزارش روز", exact: true }).click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "دریافت JSON", exact: true }).click();
  const download = await downloadPromise;
  const report = JSON.parse(await fs.readFile(await download.path(), "utf8"));
  assert.equal(report.day.day, days[0].day);
  assert.equal(report.day.snapshot_id, snapshot);
  assert.equal(report.mock, undefined);
  await page
    .getByRole("button", { name: "صفحهٔ بعدی روزها", exact: true })
    .click();
  await page.waitForFunction(
    () => document.querySelectorAll(".day-row").length === 2,
  );
  assert(calls.some((u) => u.includes("limit=5") && u.includes("offset=5")));
  await page
    .getByRole("button", { name: "صفحهٔ قبلی روزها", exact: true })
    .click();
  await page.waitForFunction(
    () => document.querySelectorAll(".day-row").length === 5,
  );
  await page
    .getByRole("textbox", { name: "جست‌وجوی روز", exact: true })
    .fill("۱۴۰۵/۰۸/۱۴");
  await page.waitForFunction(
    () => document.querySelectorAll(".day-row").length === 1,
  );
  assert(
    calls.some(
      (u) =>
        u.includes("date_from=2026-11-05") && u.includes("date_to=2026-11-05"),
    ),
  );
  await page
    .getByRole("textbox", { name: "جست‌وجوی روز", exact: true })
    .fill("2026-11-03");
  await page.waitForFunction(() =>
    document.querySelector(".day-row")?.textContent.includes("2026-11-03"),
  );
  assert.match(await page.locator(".day-row .coverage-value").innerText(), /—/);
  await page
    .getByRole("textbox", { name: "جست‌وجوی روز", exact: true })
    .fill("");
  await page.waitForFunction(
    () => document.querySelectorAll(".day-row").length === 5,
  );
  await page
    .getByRole("combobox", { name: "وضعیت روز", exact: true })
    .selectOption("attention");
  await page.waitForFunction(
    () => document.querySelectorAll(".day-row").length === 1,
  );
  assert(
    calls.some(
      (u) => u.includes("status=attention") && !u.includes("/chunks/"),
    ),
  );
  await page
    .getByRole("combobox", { name: "وضعیت روز", exact: true })
    .selectOption("all");
  await page.waitForFunction(
    () => document.querySelectorAll(".day-row").length === 5,
  );
  await page.locator(".day-row").first().click(); // expand if report was closed by pagination
  if (await page.getByRole("tab", { name: "چانک‌ها", exact: true }).count()) {
    await page.getByRole("tab", { name: "چانک‌ها", exact: true }).click();
  }
  if (process.env.TEST_OUTPUT_DIR)
    await page.screenshot({
      path: process.env.TEST_OUTPUT_DIR + "/days-desktop.png",
      fullPage: true,
    });
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
      `overflow at ${width}`,
    );
  }
  await page.setViewportSize({ width: 390, height: 1000 });
  if (process.env.TEST_OUTPUT_DIR)
    await page.screenshot({
      path: process.env.TEST_OUTPUT_DIR + "/days-mobile.png",
      fullPage: true,
    });
  // Clear stale responses on route changes; server failures never restore fixtures.
  failList = true;
  await page
    .getByRole("combobox", { name: "وضعیت روز", exact: true })
    .selectOption("processing");
  await page
    .getByRole("alert")
    .filter({ hasText: "دریافت اطلاعات از سرور ممکن نشد" })
    .waitFor();
  assert.equal(await page.locator(".day-row").count(), 0);
  failList = false;
  await page.getByRole("button", { name: "تلاش دوباره", exact: true }).click();
  await page.waitForFunction(
    () => document.querySelectorAll(".day-row").length === 1,
  );
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page
    .getByRole("combobox", { name: "وضعیت روز", exact: true })
    .selectOption("all");
  await page.waitForFunction(
    () => document.querySelectorAll(".day-row").length === 5,
  );
  slowDay = true;
  await page.locator(".day-row").nth(1).click();
  await page.locator(".day-row").nth(2).click();
  await page.waitForTimeout(700);
  assert.equal(
    await page.locator(".selection-card .selected-iso").innerText(),
    days[2].day,
  );
  assert.equal(
    await page.locator(".selection-coverage strong").innerText(),
    "—",
  );
  await page.goBack();
  await page.waitForFunction(
    () =>
      document.querySelector(".selection-card .selected-iso")?.textContent ===
      "2026-11-04",
  );
  await page.goForward();
  await page.waitForFunction(
    () =>
      document.querySelector(".selection-card .selected-iso")?.textContent ===
      "2026-11-03",
  );
  await page.locator(".chunks-table").waitFor();
  changedSnapshot = true;
  await page
    .getByRole("button", { name: "صفحهٔ بعدی چانک‌ها", exact: true })
    .click();
  await page
    .getByRole("alert")
    .filter({ hasText: "اطلاعات روز تغییر کرده است" })
    .waitFor();
  assert.equal(await page.locator(".chunk-name").count(), 0);
  changedSnapshot = false;
  failChunks = true;
  await page.locator(".day-row").nth(2).click();
  await page.locator(".day-row").nth(2).click();
  await page
    .getByRole("alert")
    .filter({ hasText: "دریافت اطلاعات از سرور ممکن نشد" })
    .waitFor();
  failChunks = false;
  await page.getByRole("button", { name: "تلاش دوباره", exact: true }).click();
  await page.waitForFunction(
    () => document.querySelectorAll(".chunk-name").length === 4,
  );
  await page.goto(base + "/#/days?day=2026-02-30");
  await page
    .getByRole("heading", { name: "تاریخ آدرس معتبر نیست", exact: true })
    .waitFor();
  assert(!calls.some((url) => url.includes("/days/2026-02-30/")));
  assert.deepEqual(errors, []);
  console.log(
    "PASS: live empty API/proxy; paginated days/chunks; month calendar; Persian/Gregorian search; status filters; null metrics; JSON provenance; error/retry; 3 responsive widths; no browser errors.",
  );
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
