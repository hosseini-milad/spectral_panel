const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const base = process.env.PANEL_URL || "http://127.0.0.1:5173";
const snapshot = "72b97835-0489-467c-8f8a-16864d14d62b";
const jobId = "8fa7f0a3-842f-4a21-bf06-f6da3cc09517";
const day = {
  day: "2026-06-22",
  schema_version: 1,
  snapshot_id: snapshot,
  status: "complete",
  processing_scope: "layer1",
  raw_records: 100,
  raw_document_bytes: null,
  chunk_size: 100,
  expected_chunks: 1,
  observed_chunks: 1,
  complete_chunks: 1,
  processing_chunks: 0,
  attention_chunks: 0,
  missing_chunks: 0,
  chunk_coverage_percent: 100,
  normalized_records: 100,
  candidate_records: 100,
  unassigned_records: { normalized_records: 0, candidate_records: 0 },
  warnings: [],
  created_at: "2026-11-12T11:00:00Z",
  updated_at: "2026-11-12T11:00:00Z",
};

const reportId = "37938ab2-b93a-4f53-af0d-38ef7da89b03";
const root = `/api/v1/days/${day.day}/overview/`;
const jobUrl = root + "jobs/" + jobId + "/";
const report = {
  id: reportId,
  schema_version: "overview_report_v1",
  day: day.day,
  window_days: 7,
  inventory_snapshot_id: snapshot,
  generated_at: day.updated_at,
  inventory_observed_at: day.updated_at,
  metrics: {
    raw_records: 100,
    chunk_coverage_percent: 100,
    normalized_records: 50,
    estimated_daily_eps: 100 / 86400,
    normalization_coverage_percent: 50,
    acceptance_rate_percent: null,
    source_groups: 7,
    unknown_source_records: 5,
    source_health: null,
    completed_chunks: 0,
    expected_chunks: 1,
    layer1_completion_percent: 0,
    operational_notices: 1,
  },
  readiness: [
    "normalize",
    "sample",
    "components",
    "representatives",
    "spectral",
    "learning",
  ].map((stage, index) => ({
    stage,
    observed_chunks: index < 4 ? 0 : null,
    expected_chunks: 1,
    percent: index < 4 ? 0 : null,
    evidence:
      index > 3
        ? "not_measured"
        : index === 1 || index === 3
          ? "output_observed"
          : "stored_complete",
  })),
  trend: Array.from({ length: 7 }, (_, i) => ({
    day: new Date(Date.UTC(2026, 5, 16 + i)).toISOString().slice(0, 10),
    raw_records: i === 0 ? null : i === 6 ? 100 : i * 100,
    coverage_percent: i === 0 ? null : 100,
    status: i === 0 ? null : "partial",
    available: i !== 0,
  })),
  notices: [{ code: "missing_chunks", count: 1, priority: "medium" }],
  latest_operation_id: null,
  sources_url: root + "reports/" + reportId + "/sources/",
  download_url: root + "reports/" + reportId + "/?download=true",
};
const groups = [20, 20, 20, 20, 10, 5, 5].map((records, i) => ({
  group_key: String(i),
  source_type: i === 6 ? null : "source-" + i,
  records,
  last_stored_at: i === 6 ? null : day.updated_at,
  health: null,
}));
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1100 },
    });
    page.setDefaultTimeout(16000);
    await page.addInitScript(() =>
      localStorage.setItem("spectral-theme", "dark"),
    );
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    let posted = 0,
      created = false,
      abort = true,
      finished = false,
      stale = false;
    const keys = [],
      pollTimes = [];
    await page.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === "/api/v1/days/")
        return route.fulfill({
          json: { count: 1, next: null, previous: null, results: [day] },
        });
      if (
        url.pathname === root + "reports/" &&
        route.request().method() === "POST"
      ) {
        posted++;
        keys.push(route.request().headers()["idempotency-key"]);
        assert.deepEqual(route.request().postDataJSON(), {
          snapshot_id: snapshot,
          window_days: 7,
        });
        if (abort) {
          abort = false;
          return route.abort("failed");
        }
        return route.fulfill({
          status: 202,
          json: {
            created: true,
            job: {
              id: jobId,
              report_id: reportId,
              status: "queued",
              status_url: jobUrl,
              worker: { online: false, busy: false },
              queue_position: 1,
            },
          },
        });
      }
      if (url.pathname === jobUrl) {
        pollTimes.push(Date.now());
        if (finished) created = true;
        return route.fulfill({
          json: {
            id: jobId,
            report_id: reportId,
            status: finished ? "succeeded" : "queued",
            worker: { online: false, busy: false },
            queue_position: 1,
            result_url: finished ? root + "reports/" + reportId + "/" : null,
          },
        });
      }
      if (url.pathname === root)
        return route.fulfill({
          json: {
            day,
            report:
              created && url.searchParams.get("window_days") !== "14"
                ? report
                : null,
            build_required: !created || stale,
            stale,
            freshness_scope: "persisted_catalog_snapshots",
          },
        });
      if (url.pathname === root + "reports/" + reportId + "/sources/") {
        const offset = Number(url.searchParams.get("offset") || 0),
          limit = Number(url.searchParams.get("limit") || 10);
        return route.fulfill({
          json: {
            count: 7,
            next: offset === 0 ? "next" : null,
            previous: offset > 0 ? "prev" : null,
            results: groups.slice(offset, offset + limit),
          },
        });
      }
      if (url.pathname === root + "reports/" + reportId + "/")
        return route.fulfill({
          json: report,
          headers: {
            "Content-Disposition": 'attachment; filename="overview-test.json"',
          },
        });
      throw new Error("Unexpected path " + url.pathname);
    });
    await page.goto(base + "/#/");
    await page
      .getByRole("heading", {
        name: "هنوز گزارش نمودارهای این روز و بازه ساخته نشده است",
      })
      .waitFor();
    assert.equal(posted, 0, "GET must not silently create reports");
    const build = page.getByRole("button", {
      name: "ایجاد گزارش نمودارها",
      exact: true,
    });
    await build.evaluate((b) => {
      b.click();
      b.click();
    });
    await page
      .getByRole("alert")
      .filter({ hasText: "ارتباط قطع شد" })
      .waitFor();
    assert.equal(posted, 1);
    await page
      .getByRole("button", { name: "تلاش دوباره", exact: true })
      .click();
    await page
      .getByRole("status")
      .filter({ hasText: "worker گزارش فعال نیست" })
      .waitFor();
    assert.equal(keys[0], keys[1]);
    const prior = pollTimes.length;
    await page.waitForTimeout(2200);
    assert.equal(pollTimes.length, prior, "must not poll every second");
    finished = true;
    await page
      .getByRole("heading", { name: "روند حجم ورودی", exact: true })
      .waitFor();
    assert(
      pollTimes.at(-1) - pollTimes.at(-2) >= 9000,
      "report polling uses 10 seconds",
    );
    await page.locator(".ov-source-table tbody tr").first().waitFor();
    assert.equal(await page.locator(".ov-source-table tbody tr").count(), 5);
    assert.equal(await page.locator('rect[data-records="unknown"]').count(), 1);
    assert.equal(await page.locator('rect[data-records="100"]').count(), 2);
    assert(
      !/NaN|Infinity/.test(
        await page.locator(".ov-trend-svg").getAttribute("viewBox"),
      ),
    );
    assert.equal(await page.locator(".ov-unknown-track").count(), 2);
    assert.match(await page.locator(".ov-rate-note").innerText(), /دقت تشخیص/);
    const sourceCard = page.locator(".ov-sources");
    await sourceCard.getByRole("button", { name: "بعدی", exact: true }).click();
    await page.waitForFunction(
      () => document.querySelectorAll(".ov-source-table tbody tr").length === 2,
    );
    assert.match(await sourceCard.innerText(), /نامشخص/);
    const downloading = page.waitForEvent("download");
    await page
      .getByRole("link", { name: "دریافت JSON گزارش", exact: true })
      .click();
    const download = await downloading;
    assert.equal(
      JSON.parse(await fs.readFile(await download.path(), "utf8")).id,
      reportId,
    );
    if (process.env.TEST_OUTPUT_DIR)
      await page.screenshot({
        path: process.env.TEST_OUTPUT_DIR + "/overview-desktop.png",
        fullPage: true,
      });
    await page.setViewportSize({ width: 390, height: 844 });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    if (process.env.TEST_OUTPUT_DIR)
      await page.screenshot({
        path: process.env.TEST_OUTPUT_DIR + "/overview-mobile.png",
        fullPage: true,
      });
    await page.reload();
    await page
      .getByRole("heading", { name: "روند حجم ورودی", exact: true })
      .waitFor();
    assert.equal(posted, 2, "reload reads persisted report, no extra POST");
    stale = true;
    await page
      .getByRole("button", { name: "بازخوانی اطلاعات", exact: true })
      .click();
    await page
      .getByRole("status")
      .filter({ hasText: "پس از تولید این گزارش تغییر کرده" })
      .waitFor();
    await page.getByLabel("بازهٔ نمودار", { exact: true }).selectOption("14");
    await page
      .getByRole("heading", {
        name: "هنوز گزارش نمودارهای این روز و بازه ساخته نشده است",
      })
      .waitFor();
    assert.equal(
      await page.locator(".ov-trend-svg").count(),
      0,
      "different window never shows stale chart from prior query",
    );
    assert.deepEqual(errors, []);
    console.log(
      "PASS: stored-report-only GET, explicit generation, double-click/retry keys, 10s polling, missing-day gaps, measured/unknown readiness, paginated real source groups, JSON download, persisted reload, staleness/window guards, responsive chart and no browser errors.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
