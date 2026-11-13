const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const base = process.env.PANEL_URL || "http://127.0.0.1:5173";
const day = "2026-06-22";
const snapshot = "72b97835-0489-467c-8f8a-16864d14d62b";
const settings = {
  chunk_size: 20000,
  batch_size: 2000,
  sample_ratio: 0.1,
  representative_ratio: 0.1,
  neighbors: 12,
  threshold: 0.95,
  degree_cap: 20,
};
let operationPosts = 0,
  refreshPosts = 0,
  refreshed = false;
const reads = [];
const inventory = {
  day,
  snapshot_id: snapshot,
  raw_records: 1000000,
  chunk_size: 20000,
  expected_chunks: 50,
  updated_at: "2026-11-13T09:00:00Z",
};
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium",
    headless: true,
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1100 },
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/api/v1/**", async (route) => {
      const req = route.request(),
        url = new URL(req.url());
      if (url.pathname.endsWith("/operations/")) {
        operationPosts++;
        throw new Error("Resume must not submit operations");
      }
      if (
        url.pathname.endsWith("/operations/progress/") &&
        req.method() === "POST"
      ) {
        refreshPosts++;
        assert(req.headers()["idempotency-key"]);
        assert.equal(req.postDataJSON().snapshot_id, snapshot);
        return route.fulfill({
          status: 202,
          json: {
            created: true,
            job: {
              status: "queued",
              status_url: `/api/v1/days/${day}/operations/progress/jobs/00000000-0000-4000-8000-000000000001/`,
              worker: { online: true },
              queue_position: 1,
            },
          },
        });
      }
      if (url.pathname.includes("/operations/progress/jobs/")) {
        refreshed = true;
        return route.fulfill({
          json: {
            status: "succeeded",
            status_url: url.pathname,
            worker: { online: true },
            queue_position: null,
          },
        });
      }
      if (url.pathname.endsWith("/operations/progress/")) {
        reads.push({ time: Date.now(), params: url.searchParams });
        const offset = Number(url.searchParams.get("offset") || 0),
          filter = url.searchParams.get("status");
        const indices = Array.from({ length: 40 }, (_, i) => i).filter(
          (i) => i !== 30,
        );
        const all = refreshed
          ? Array.from({ length: 50 }, (_, i) => i)
          : indices;
        const rows =
          filter === "partial" && !refreshed
            ? [30]
            : filter === "partial"
              ? []
              : all;
        return route.fulfill({
          json: {
            snapshot_id: snapshot,
            inventory_observed_at: inventory.updated_at,
            total_chunks: 50,
            complete_chunks: refreshed ? 50 : 39,
            remaining_chunks: refreshed ? 0 : 11,
            partial_chunks: refreshed ? 0 : 1,
            attention_chunks: 0,
            reserved_remaining_chunks: refreshed ? 0 : 5,
            first_remaining_chunk: refreshed ? null : 30,
            highest_completed_chunk: refreshed ? 49 : 39,
            completed_ranges: refreshed
              ? [{ start_chunk: 0, end_chunk: 49, count: 50 }]
              : [
                  { start_chunk: 0, end_chunk: 29, count: 30 },
                  { start_chunk: 31, end_chunk: 39, count: 9 },
                ],
            completed_ranges_truncated: false,
            stage_counts: {
              normalize: 40,
              sample: 40,
              components: 40,
              representatives: refreshed ? 50 : 39,
            },
            suggested_selection: refreshed
              ? null
              : {
                  start_chunk: 30,
                  end_chunk: 39,
                  count: 10,
                  reused_count: 9,
                  remaining_count: 1,
                },
            latest_run_settings: { ...settings, sample_ratio: 0.2 },
            latest_settings_compatible: true,
            count: rows.length,
            results: rows.slice(offset, offset + 10).map((i) => ({
              chunk_index: i,
              status: i === 30 ? "partial" : "complete",
              reserved: false,
              stages: {
                normalize: true,
                sample: true,
                components: true,
                representatives: i !== 30,
              },
            })),
          },
        });
      }
      if (url.pathname === "/api/v1/operations/runs/")
        return route.fulfill({
          json: { count: 0, results: [], next: null, previous: null },
        });
      if (url.pathname === `/api/v1/days/${day}/`)
        return route.fulfill({ json: inventory });
      if (url.pathname === "/api/v1/days/")
        return route.fulfill({
          json: { count: 1, results: [inventory], next: null, previous: null },
        });
      throw new Error("Unexpected request " + url.pathname);
    });
    await page.goto(base + "/#/operations?day=" + day);
    const panel = page.getByRole("region", { name: "آمار پردازش چانک‌ها" });
    await panel.getByText("۳۹ از ۵۰", { exact: true }).waitFor();
    await panel
      .getByRole("button", { name: "ادامهٔ پردازش از ۳۰ تا ۳۹", exact: true })
      .click();
    assert.equal(
      await page.getByLabel("دامنهٔ چانک‌ها", { exact: true }).inputValue(),
      "range",
    );
    assert.equal(
      await page.getByLabel("از چانک", { exact: true }).inputValue(),
      "30",
    );
    assert.equal(
      await page.getByLabel("تا چانک", { exact: true }).inputValue(),
      "39",
    );
    assert.equal(operationPosts, 0);
    await panel.locator("summary").click();
    await panel.getByRole("button", { name: "بعدی", exact: true }).click();
    await page.waitForFunction(
      () =>
        document.querySelector(".op-progress tbody tr td")?.textContent ===
        "۱۰",
    );
    await panel.getByLabel("فیلتر آمار چانک‌ها").selectOption("partial");
    await page.waitForFunction(
      () =>
        document.querySelector(".op-progress tbody tr td")?.textContent ===
        "۳۰",
    );
    await panel
      .getByRole("button", {
        name: "استفاده از تنظیمات آخرین اجرا",
        exact: true,
      })
      .click();
    await page.waitForFunction(() =>
      document.querySelector(".op-resume")?.textContent.includes("۳۰"),
    );
    await page.waitForTimeout(300);
    assert(reads.some((r) => r.params.get("sample_ratio") === "0.2"));
    const baseline = reads.length;
    await page.waitForTimeout(1800);
    assert.equal(reads.length, baseline, "no one-second progress polling");
    await page.waitForTimeout(8500);
    assert(reads.length > baseline, "progress must update every ten seconds");
    await page.getByRole("button", { name: "تم تیره", exact: true }).click();
    if (process.env.TEST_OUTPUT_DIR)
      await page.screenshot({
        path: process.env.TEST_OUTPUT_DIR + "/operation-progress-desktop.png",
        fullPage: true,
      });
    await page.setViewportSize({ width: 390, height: 844 });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      "responsive page must not overflow",
    );
    if (process.env.TEST_OUTPUT_DIR)
      await page.screenshot({
        path: process.env.TEST_OUTPUT_DIR + "/operation-progress-mobile.png",
        fullPage: true,
      });
    await panel
      .getByRole("button", { name: "بازخوانی آمار از خروجی‌ها", exact: true })
      .click();
    assert.equal(refreshPosts, 1);
    await panel
      .getByText("۵۰ از ۵۰", { exact: true })
      .waitFor({ timeout: 16000 });
    assert(
      await panel
        .getByRole("button", { name: "ادامهٔ پردازش", exact: true })
        .isDisabled(),
    );
    assert.equal(operationPosts, 0);
    assert.deepEqual(errors, []);
    console.log(
      "PASS: 39 complete with hole at 30; resume prefills range without POST; pagination/filter; previous settings; 10-second polling; explicit refresh; all complete; responsive layout.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
