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

const runs = [];
const keys = [];
let abortFirst = true;
let posts = 0;
let running = false;
const readTimes = [];
const bodies = [];
const makeRun = (id, body) => ({
  id,
  day: day.day,
  status: "queued",
  created_at: day.updated_at,
  started_at: null,
  finished_at: null,
  updated_at: day.updated_at,
  observed_at: day.updated_at,
  chunk_start: body.selection.start_chunk ?? body.selection.chunk_index ?? 0,
  chunk_end: body.selection.end_chunk ?? body.selection.chunk_index ?? 24,
  chunk_count: 10,
  settings: body.settings,
  selection: body.selection,
  current_chunk: null,
  current_stage: null,
  error: null,
  inventory_refresh: "pending",
  configuration_version: "chunk_operations_v1",
  configuration_hash: "a".repeat(64),
  progress: {
    completed_units: 0,
    total_units: 40,
    reused_units: 0,
    percent: 0,
    current_task_percent: null,
  },
  stages: ["normalize", "sample", "components", "representatives"].map(
    (stage) => ({
      stage,
      status: "queued",
      completed_units: 0,
      total_units: 10,
      percent: 0,
      input: null,
      output: null,
    }),
  ),
  worker: { online: true, busy: false, heartbeat_age_seconds: 1 },
  queue_position: 1,
  poll_after_seconds: 10,
});
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1050 },
    });
    page.setDefaultTimeout(16000);
    await page.addInitScript(() =>
      localStorage.setItem("spectral-theme", "dark"),
    );
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url());
      if (route.request().method() === "POST") {
        assert.equal(url.pathname, `/api/v1/days/${day.day}/operations/`);
        posts++;
        const key = route.request().headers()["idempotency-key"];
        keys.push(key);
        const body = route.request().postDataJSON();
        bodies.push(body);
        assert.equal(body.snapshot_id, snapshot);
        let run = runs.find((r) => r._key === key);
        if (!run) {
          run = {
            ...makeRun(
              `00000000-0000-4000-8000-${String(runs.length + 1).padStart(12, "0")}`,
              body,
            ),
            _key: key,
          };
          runs.unshift(run);
        }
        if (abortFirst) {
          abortFirst = false;
          return route.abort("failed");
        }
        return route.fulfill({
          status: 202,
          json: { created: posts !== 2, run },
        });
      }
      if (url.pathname === "/api/v1/operations/runs/")
        return route.fulfill({
          json: {
            count: runs.length,
            next: null,
            previous: null,
            results: runs,
          },
        });
      const matched = url.pathname.match(/\/runs\/([^/]+)\//);
      if (matched) {
        const run = runs.find((r) => r.id === matched[1]);
        assert(run);
        if (url.pathname.endsWith("/tasks/"))
          return route.fulfill({
            json: {
              count: 40,
              next: "next",
              previous: null,
              results: [
                {
                  position: 0,
                  chunk_index: run.chunk_start,
                  stage: "normalize",
                  status: running ? "succeeded" : "pending",
                  started_at: null,
                  finished_at: null,
                  result: running
                    ? {
                        input: 20000,
                        output: 20000,
                        reused: false,
                        unit: "records",
                      }
                    : null,
                  error: null,
                },
              ],
            },
          });
        if (url.pathname.endsWith("/events/"))
          return route.fulfill({
            json: {
              count: 1,
              next: null,
              previous: null,
              results: [
                {
                  sequence: 1,
                  time: day.updated_at,
                  level: "info",
                  code: running ? "stage_started" : "run_started",
                  chunk_index: run.chunk_start,
                  stage: "normalize",
                },
              ],
            },
          });
        readTimes.push(Date.now());
        return route.fulfill({
          json: running
            ? {
                ...run,
                status: "running",
                current_chunk: run.chunk_start,
                current_stage: "sample",
                progress: { ...run.progress, completed_units: 2, percent: 5 },
                stages: run.stages.map((s) =>
                  s.stage === "normalize"
                    ? {
                        ...s,
                        completed_units: 2,
                        percent: 20,
                        input: 40000,
                        output: 40000,
                      }
                    : s,
                ),
              }
            : run,
        });
      }
      if (url.pathname === `/api/v1/days/${day.day}/`)
        return route.fulfill({
          json: {
            ...day,
            raw_records: 500000,
            chunk_size: 20000,
            expected_chunks: 25,
          },
        });
      if (url.pathname === "/api/v1/days/")
        return route.fulfill({
          json: { count: 1, next: null, previous: null, results: [day] },
        });
      throw new Error("Unexpected request " + url.pathname);
    });
    await page.goto(base + "/#/operations");
    await page.getByLabel("روز پردازش", { exact: true }).selectOption(day.day);
    const scope = page.getByLabel("دامنهٔ چانک‌ها", { exact: true });
    await scope.selectOption("range");
    await page.getByLabel("از چانک", { exact: true }).fill("1");
    await page.getByLabel("تا چانک", { exact: true }).fill("10");
    const submit = page.getByRole("button", {
      name: "ثبت همهٔ مراحل در صف",
      exact: true,
    });
    await page.waitForFunction(
      () => !document.querySelector(".op-run-all")?.disabled,
    );
    await submit.evaluate((b) => {
      b.click();
      b.click();
    });
    await page
      .getByRole("alert")
      .filter({ hasText: "ارتباط قطع شد" })
      .waitFor();
    assert.equal(posts, 1);
    await submit.click();
    await page
      .getByText("درصد داخل محاسبه اندازه‌گیری نشده است.", { exact: false })
      .waitFor();
    assert.equal(posts, 2);
    assert.equal(keys[0], keys[1]);
    assert.deepEqual(bodies[1].selection, {
      mode: "range",
      start_chunk: 1,
      end_chunk: 10,
    });
    const baseline = readTimes.length;
    running = true;
    await page.waitForTimeout(2200);
    assert.equal(readTimes.length, baseline, "must not poll every second");
    await page.waitForFunction(
      () =>
        document.querySelector('[aria-label="پیشرفت کل عملیات"]')?.value === 5,
      null,
      { timeout: 14000 },
    );
    assert(
      readTimes.at(-1) - readTimes.at(-2) >= 9000,
      "progress polling must use ten seconds",
    );
    assert.equal(
      await page
        .locator('[aria-label="پیشرفت کل عملیات"]')
        .getAttribute("value"),
      "5",
    );
    // Enqueue next range while the first run is still running.
    await page.getByLabel("از چانک", { exact: true }).fill("11");
    await page.getByLabel("تا چانک", { exact: true }).fill("20");
    await submit.click();
    await page.waitForFunction(() => location.hash.includes("000000000002"));
    assert.equal(posts, 3);
    assert.deepEqual(bodies[2].selection, {
      mode: "range",
      start_chunk: 11,
      end_chunk: 20,
    });
    await scope.selectOption("page");
    await page.getByLabel("صفحهٔ چانک‌ها", { exact: true }).fill("2");
    await submit.click();
    await page.waitForFunction(() => location.hash.includes("000000000003"));
    assert.deepEqual(bodies[3].selection, {
      mode: "page",
      page: 2,
      page_size: 10,
    });
    await scope.selectOption("single");
    await page.getByLabel("از چانک", { exact: true }).fill("3");
    await page
      .getByRole("button", { name: "اجرای نرمال‌سازی", exact: true })
      .click();
    await page.waitForFunction(() => location.hash.includes("000000000004"));
    assert.deepEqual(bodies[4].selection, { mode: "single", chunk_index: 3 });
    assert.equal(bodies[4].stage, "normalize");
    await scope.selectOption("all");
    await submit.click();
    await page.waitForFunction(() => location.hash.includes("000000000005"));
    assert.deepEqual(bodies[5].selection, { mode: "all" });
    await page.reload();
    await page
      .getByText("درصد داخل محاسبه اندازه‌گیری نشده است.", { exact: false })
      .waitFor();
    assert.equal(posts, 6, "reload must resume status, not submit");
    if (process.env.TEST_OUTPUT_DIR)
      await page.screenshot({
        path: process.env.TEST_OUTPUT_DIR + "/operations-real-desktop.png",
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
        path: process.env.TEST_OUTPUT_DIR + "/operations-real-mobile.png",
        fullPage: true,
      });
    assert.deepEqual(errors, []);
    console.log(
      "PASS: server days; range 1–10 and 11–20; page/single/all; double-click and retry keys; 10-second truthful polling; queued next request while running; persisted reload; events/tasks and responsive layout.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
