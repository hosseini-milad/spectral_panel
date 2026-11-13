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
let cancelPosts = 0;
let finishCancelled = false;
let showTelemetry = false;
let retryPosts = 0;
const retryKeys = [];
let abortRetry = true;
const readTimes = [];
const bodies = [];
const makeRun = (id, body) => ({
  id,
  day: day.day,
  status: "queued",
  cancel_requested: false,
  cancel_requested_at: null,
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
      if (
        route.request().method() === "POST" &&
        url.pathname.endsWith("/retry-failed/")
      ) {
        retryPosts++;
        const key = route.request().headers()["idempotency-key"];
        retryKeys.push(key);
        assert(key);
        assert.deepEqual(route.request().postDataJSON(), {
          stage_timeout_seconds: 300,
        });
        const sourceId = url.pathname.match(/\/runs\/([^/]+)\//)[1];
        const source = runs.find((r) => r.id === sourceId);
        let retry = runs.find((r) => r._retryKey === key);
        if (!retry) {
          retry = {
            ...makeRun("00000000-0000-4000-8000-000000000099", {
              settings: { ...source.settings, stage_timeout_seconds: 300 },
              selection: { mode: "chunks", chunk_indices: [0, 3] },
            }),
            chunk_start: 0,
            chunk_end: 3,
            chunk_count: 2,
            retry_of_run_id: sourceId,
            _retryKey: key,
          };
          runs.unshift(retry);
        }
        if (abortRetry) {
          abortRetry = false;
          return route.abort("failed");
        }
        return route.fulfill({
          status: 202,
          json: { created: false, run: retry },
        });
      }
      if (
        route.request().method() === "POST" &&
        url.pathname.endsWith("/cancel/")
      ) {
        cancelPosts++;
        const id = url.pathname.match(/\/runs\/([^/]+)\//)[1];
        const run = runs.find((r) => r.id === id);
        assert.deepEqual(route.request().postDataJSON(), {});
        run.cancel_requested = true;
        run.cancel_requested_at = day.updated_at;
        run.status = running ? "running" : "cancelled";
        run.current_chunk = running ? run.chunk_start : null;
        return route.fulfill({ status: running ? 202 : 200, json: run });
      }
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
      if (url.pathname.endsWith("/operations/progress/"))
        return route.fulfill({
          json: {
            snapshot_id: snapshot,
            inventory_observed_at: day.updated_at,
            total_chunks: 25,
            complete_chunks: 0,
            remaining_chunks: 25,
            partial_chunks: 0,
            attention_chunks: 0,
            reserved_remaining_chunks: 0,
            first_remaining_chunk: 0,
            highest_completed_chunk: null,
            completed_ranges: [],
            completed_ranges_truncated: false,
            stage_counts: {
              normalize: 0,
              sample: 0,
              components: 0,
              representatives: 0,
            },
            suggested_selection: {
              start_chunk: 0,
              end_chunk: 9,
              count: 10,
              reused_count: 0,
              remaining_count: 10,
            },
            latest_run_settings: null,
            latest_settings_compatible: false,
            count: 0,
            results: [],
          },
        });
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
        if (url.pathname.endsWith("/tasks/")) {
          if (Number(url.searchParams.get("offset")) > 0)
            await new Promise((resolve) => setTimeout(resolve, 300));
          return route.fulfill({
            json: {
              count: 40,
              next: "next",
              previous: null,
              results: [
                {
                  position: Number(url.searchParams.get("offset") || 0),
                  chunk_index:
                    run.chunk_start +
                    Math.floor(Number(url.searchParams.get("offset") || 0) / 4),
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
        }
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
        if (run.cancel_requested) {
          const stopped = finishCancelled || run.status === "cancelled";
          return route.fulfill({
            json: {
              ...run,
              status: stopped ? "cancelled" : "running",
              current_chunk: stopped ? null : run.chunk_start,
              current_stage: stopped ? null : "sample",
              progress: {
                ...run.progress,
                completed_units: stopped ? 4 : 2,
                percent: stopped ? 10 : 5,
              },
            },
          });
        }
        readTimes.push(Date.now());
        return route.fulfill({
          json: running
            ? {
                ...run,
                status: "running",
                ...(showTelemetry
                  ? {
                      execution_policy: "continue_on_chunk_error_v1",
                      failed_chunks: [run.chunk_start],
                      recent_errors: [
                        {
                          chunk_index: run.chunk_start,
                          stage: "components",
                          error: { code: "stage_timeout" },
                          finished_at: day.updated_at,
                        },
                      ],
                      current_task: {
                        chunk_index: run.chunk_start + 1,
                        stage: "representatives",
                        started_at: day.updated_at,
                        elapsed_seconds: 200,
                        timeout_seconds: 300,
                        remaining_seconds: 100,
                        last_output_at: day.updated_at,
                        seconds_since_output: 300,
                        phase: "centralities",
                        phase_elapsed_seconds: 300,
                      },
                    }
                  : {}),
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
    showTelemetry = true;
    await page.reload();
    await page
      .locator(".op-task-runtime")
      .getByText("محاسبهٔ مرکزیت گره‌ها", { exact: true })
      .waitFor();
    await page
      .locator(".op-task-runtime")
      .getByText("۳ دقیقه و ۲۰ ثانیه", { exact: true })
      .waitFor();
    await page
      .locator(".op-task-runtime")
      .getByText("۵ دقیقه و ۰ ثانیه", { exact: true })
      .waitFor();
    await page
      .locator(".op-chunk-failures")
      .getByText("مهلت مرحله تمام شد", { exact: false })
      .waitFor();
    const cancel = page.getByRole("button", {
      name: "لغو ادامهٔ پردازش",
      exact: true,
    });
    await cancel.evaluate((button) => {
      button.click();
      button.click();
    });
    await page
      .getByRole("button", { name: "در انتظار توقف", exact: true })
      .waitFor();
    assert.equal(
      cancelPosts,
      1,
      "double click must not submit two cancellation requests",
    );
    assert(
      await page
        .getByRole("button", { name: "در انتظار توقف", exact: true })
        .isDisabled(),
    );
    await page
      .getByText("درخواست لغو ثبت شد؛ چانک", { exact: false })
      .waitFor();
    await page.reload();
    await page
      .getByRole("button", { name: "در انتظار توقف", exact: true })
      .waitFor();
    assert.equal(
      cancelPosts,
      1,
      "reload must read persisted cancellation, not POST again",
    );
    finishCancelled = true;
    await page
      .locator(".op-execution-state.cancelled")
      .waitFor({ timeout: 14000 });
    assert.equal(
      await page
        .getByRole("button", { name: "لغو ادامهٔ پردازش", exact: true })
        .count(),
      0,
    );
    assert.equal(
      await page
        .getByLabel("پیشرفت کل عملیات", { exact: true })
        .getAttribute("value"),
      "10",
      "cancellation must not fake 100 percent",
    );
    assert.equal(posts, 6, "cancelling must not create another operation");
    running = false;
    const queuedId = runs[1].id;
    await page.goto(base + "/#/operations?day=" + day.day + "&run=" + queuedId);
    await page
      .getByRole("button", { name: "لغو ادامهٔ پردازش", exact: true })
      .click();
    await page.locator(".op-execution-state.cancelled").waitFor();
    assert.equal(cancelPosts, 2);
    assert(
      runs.some((r) => !r.cancel_requested),
      "other queued operations must be unaffected",
    );
    assert.equal(await page.locator("#operation-queue-title").count(), 0);
    assert.equal(await page.locator(".op-progress-details").count(), 0);
    assert.equal(
      await page
        .locator(
          ".op-mock-notice,.op-local-note,.op-stage-note,.op-page-heading .page-description",
        )
        .count(),
      0,
    );
    const source = runs.find((r) => r.id.endsWith("000000000005"));
    Object.assign(source, {
      status: "failed",
      cancel_requested: false,
      failed_chunks: [0, 3],
      recent_errors: [
        {
          chunk_index: 0,
          stage: "sample",
          error: { code: "stage_timeout" },
          finished_at: day.updated_at,
        },
      ],
      error: { code: "chunks_failed" },
    });
    await page.goto(
      base + "/#/operations?day=" + day.day + "&run=" + source.id,
    );
    const retryButton = page.getByRole("button", {
      name: "اجرای مجدد ۲ چانک ناموفق",
      exact: true,
    });
    await retryButton.waitFor();
    const tasks = page
      .locator("section.op-card")
      .filter({ has: page.locator(".op-task-table") });
    const nextTaskPage = tasks.getByRole("button", {
      name: "بعدی",
      exact: true,
    });
    await nextTaskPage.scrollIntoViewIfNeeded();
    const scrollBefore = await page.evaluate(() => window.scrollY);
    await nextTaskPage.click();
    await page.waitForTimeout(80);
    assert.equal(
      await page.locator(".op-task-table tbody tr").count(),
      1,
      "Do not remove current data while a page loads",
    );
    await page.waitForFunction(
      () =>
        document.querySelector(".op-task-table tbody td")?.textContent === "۲",
    );
    assert(
      Math.abs((await page.evaluate(() => window.scrollY)) - scrollBefore) < 5,
      "Task pagination must preserve document scroll",
    );
    await retryButton.evaluate((button) => {
      button.click();
      button.click();
    });
    await page
      .getByRole("alert")
      .filter({ hasText: "دریافت پاسخ اجرای مجدد" })
      .waitFor();
    assert.equal(retryPosts, 1);
    await retryButton.click();
    await page.waitForFunction(() => location.hash.includes("000000000099"));
    assert.equal(retryPosts, 2);
    assert.equal(retryKeys[0], retryKeys[1]);
    assert.equal(runs.filter((r) => r._retryKey).length, 1);
    await page
      .getByText("اجرای مجدد چانک‌های ناموفق · ۲ چانک", { exact: true })
      .waitFor();
    assert.deepEqual(runs[0].selection, {
      mode: "chunks",
      chunk_indices: [0, 3],
    });
    assert.deepEqual(source.failed_chunks, [0, 3]);
    await page.goto(base + "/#/operations?day=" + day.day);
    await page.waitForFunction(() => location.hash.includes("000000000099"));
    assert.equal(retryPosts, 2, "Recover latest run without submitting again");
    assert.deepEqual(errors, []);
    console.log(
      "PASS: server days; range 1–10 and 11–20; page/single/all; double-click and retry keys; 10-second truthful polling; queued next request while running; persisted reload; events/tasks; graceful cancellation, duplicate-click guard, persisted pending cancellation, truthful cancelled progress, queued cancellation; sparse failed-chunk retry with preserved key; latest-run recovery; removed sections; stable pagination scroll; five-minute default and responsive layout.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
