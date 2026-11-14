const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const base = process.env.PANEL_URL || "http://127.0.0.1:5173";
const dateA = "2026-06-22",
  dateB = "2026-06-23",
  snapshot = "72b97835-0489-467c-8f8a-16864d14d62b";
const settings = {
  chunk_size: 100,
  batch_size: 100,
  sample_ratio: 0.1,
  representative_ratio: 0.1,
  neighbors: 12,
  threshold: 0.95,
  degree_cap: 20,
  stage_timeout_seconds: 300,
};
const day = (value) => ({
  day: value,
  snapshot_id: snapshot,
  raw_records: 1000,
  chunk_size: 100,
  expected_chunks: 10,
  observed_chunks: 0,
  updated_at: "2026-11-14T08:00:00Z",
});
function run(n, date, status = "queued") {
  return {
    id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
    day: date,
    status,
    chunk_start: n,
    chunk_end: n + 2,
    chunk_count: 3,
    selection: { mode: "range", start_chunk: n, end_chunk: n + 2 },
    settings,
    created_at: day(date).updated_at,
    updated_at: day(date).updated_at,
    observed_at: day(date).updated_at,
    current_chunk: status === "running" ? n : null,
    current_stage: status === "running" ? "representatives" : null,
    cancel_requested: false,
    error: null,
    inventory_refresh: "pending",
    configuration_version: "v1",
    progress: {
      completed_units: 2,
      total_units: 12,
      reused_units: 0,
      percent: 16,
      processed_percent: 16,
    },
    stages: ["normalize", "sample", "components", "representatives"].map(
      (stage) => ({
        stage,
        status:
          status === "running" && stage === "representatives"
            ? "running"
            : "queued",
        completed_units: 0,
        total_units: 3,
        percent: 0,
        input: null,
        output: null,
      }),
    ),
    worker: { online: true, busy: true, heartbeat_age_seconds: 1 },
    queue_position: status === "queued" ? n - 1 : null,
  };
}
const active = run(1, dateA, "running");
const waiting = Array.from({ length: 6 }, (_, i) =>
  run(i + 2, i === 5 ? dateA : dateB),
);
const all = [active, ...waiting];
let offline = false,
  failQueue = false,
  posts = 0;
const reads = [];
const clears = [];
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium",
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1100 },
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.addInitScript(() => {
      if (!localStorage.getItem("spectral-theme"))
        localStorage.setItem("spectral-theme", "dark");
    });
    await page.route("**/api/v1/**", async (route) => {
      const req = route.request(),
        url = new URL(req.url());
      if (
        req.method() === "POST" &&
        url.pathname === "/api/v1/operations/queue/clear/"
      ) {
        clears.push(req.postDataJSON());
        if (clears.length === 1) {
          // Cancellation succeeded but the response was lost. A new submission
          // must survive a retry using the originally pinned cutoff.
          waiting.splice(0, waiting.length, run(8, dateB));
          return route.abort("failed");
        }
        return route.fulfill({
          json: {
            cancelled_count: 0,
            skipped_count: 0,
            remaining_queued_count: 1,
          },
        });
      }
      if (req.method() === "POST") {
        posts++;
        throw Error("Queue navigation must be read-only");
      }
      if (url.pathname === "/api/v1/operations/queue/") {
        if (failQueue)
          return route.fulfill({
            status: 503,
            json: { code: "database_unavailable" },
          });
        reads.push({ time: Date.now(), url: url.search });
        const selected = waiting.filter(
          (r) =>
            !url.searchParams.get("day") ||
            r.day === url.searchParams.get("day"),
        );
        const offset = Number(url.searchParams.get("offset") || 0);
        return route.fulfill({
          json: {
            observed_at: day(dateA).updated_at,
            poll_after_seconds: 10,
            execution_state: offline ? "offline" : "running",
            worker: {
              online: !offline,
              busy: !offline,
              heartbeat_age_seconds: offline ? 120 : 1,
            },
            active_run: offline ? null : active,
            unconfirmed_runs: offline ? [active] : [],
            queued_total: waiting.length,
            count: selected.length,
            next: offset + 5 < selected.length ? "next" : null,
            previous: offset ? "previous" : null,
            results: selected.slice(offset, offset + 5),
          },
        });
      }
      if (url.pathname === "/api/v1/days/")
        return route.fulfill({
          json: {
            count: 2,
            next: null,
            previous: null,
            results: [day(dateA), day(dateB)],
          },
        });
      const date = /\/days\/([^/]+)\//.exec(url.pathname)?.[1];
      if (date && url.pathname.endsWith("/operations/progress/"))
        return route.fulfill({
          json: {
            snapshot_id: snapshot,
            inventory_observed_at: day(date).updated_at,
            total_chunks: 10,
            complete_chunks: 0,
            remaining_chunks: 10,
            partial_chunks: 0,
            attention_chunks: 0,
            reserved_remaining_chunks: 5,
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
            suggested_selection: null,
            latest_settings_compatible: false,
            count: 0,
            results: [],
          },
        });
      if (date) return route.fulfill({ json: day(date) });
      const id = /\/runs\/([^/]+)\//.exec(url.pathname)?.[1];
      if (id) {
        const found = all.find((r) => r.id === id);
        assert(found);
        return route.fulfill({
          json:
            url.pathname.endsWith("/tasks/") ||
            url.pathname.endsWith("/events/")
              ? { count: 0, next: null, previous: null, results: [] }
              : found,
        });
      }
      throw Error("Unexpected " + url.pathname);
    });
    await page.goto(base + "/#/jobs?day=" + dateB + "&run=" + waiting[0].id);
    const queue = page.getByRole("region", { name: "صف اجراها", exact: true });
    await queue.getByText("فعال روی سرور", { exact: true }).waitFor();
    assert.equal(
      await page.locator(".navigation a.active").first().textContent(),
      "صف اجراها",
    );
    assert.equal(
      await queue.locator(".execution-active bdi").textContent(),
      active.id.slice(0, 8),
    );
    assert.equal(
      await queue.locator(".execution-waiting-row.is-selected").count(),
      1,
    );
    assert(
      !page.url().includes(active.id),
      "Viewing a queued item must not imply it is active",
    );
    await queue.getByLabel("فیلتر روز اجرا").selectOption(dateB);
    await page.waitForFunction(
      () => document.querySelectorAll(".execution-waiting-row").length === 5,
    );
    await page.waitForTimeout(100);
    assert(reads.some((r) => r.url.includes("day=" + dateB)));
    assert.equal(
      await queue.locator(".execution-active bdi").textContent(),
      active.id.slice(0, 8),
      "Another day active must remain visible",
    );
    await queue.getByLabel("فیلتر روز اجرا").selectOption("");
    await queue.getByRole("button", { name: "بعدی", exact: true }).click();
    await page.waitForFunction(
      () => document.querySelectorAll(".execution-waiting-row").length === 1,
    );
    await queue
      .getByRole("button", {
        name: "مشاهده اجرای " + waiting[5].id,
        exact: true,
      })
      .click();
    await page.waitForFunction(
      (id) => location.hash.includes(id),
      waiting[5].id,
    );
    assert(page.url().includes("day=" + dateA));
    assert(page.url().includes("/operations?"));
    await queue.waitFor({ state: "detached" });
    assert.equal(await queue.count(), 0, "Operations must not embed the queue");
    const queueLink = page
      .locator("main")
      .getByRole("link", { name: "صف اجراها", exact: true });
    assert(
      (await queueLink.getAttribute("href")).includes(waiting[5].id),
      "Queue shortcut preserves the viewed run",
    );
    const queueReads = reads.length;
    await page.waitForTimeout(500);
    assert.equal(
      reads.length,
      queueReads,
      "Operations does not fetch the queue",
    );
    await page.goBack();
    await queue
      .getByRole("button", {
        name: "مشاهده اجرای " + waiting[5].id,
        exact: true,
      })
      .waitFor();
    assert(page.url().includes("offset=5"), "Back restores the queue page");
    await queue
      .getByRole("button", { name: "مشاهدهٔ اجرای فعال", exact: true })
      .click();
    await page.waitForFunction(
      (id) =>
        location.hash.includes(id) && location.hash.includes("/operations?"),
      active.id,
    );
    assert(page.url().includes("day=" + dateA));
    await page.goBack();
    await queue.getByText("فعال روی سرور", { exact: true }).waitFor();
    const before = reads.length;
    await page.waitForTimeout(1800);
    assert.equal(reads.length, before);
    await page.waitForTimeout(8500);
    assert(reads.length > before);
    assert(
      reads.at(-1).time - reads.at(-2).time >= 9000,
      "Queue uses ten-second polling",
    );
    if (process.env.TEST_OUTPUT_DIR)
      await queue.screenshot({
        path: process.env.TEST_OUTPUT_DIR + "/execution-queue-desktop.png",
      });
    await page.setViewportSize({ width: 390, height: 844 });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    if (process.env.TEST_OUTPUT_DIR)
      await queue.screenshot({
        path: process.env.TEST_OUTPUT_DIR + "/execution-queue-mobile.png",
      });
    await page.setViewportSize({ width: 1440, height: 1100 });
    await page.evaluate(() => localStorage.setItem("spectral-theme", "light"));
    await page.reload();
    await queue.getByText("فعال روی سرور", { exact: true }).waitFor();
    if (process.env.TEST_OUTPUT_DIR)
      await page.screenshot({
        path: process.env.TEST_OUTPUT_DIR + "/execution-queue-light.png",
        fullPage: true,
      });
    failQueue = true;
    await queue
      .getByRole("button", { name: "بازخوانی صف اجراها", exact: true })
      .click();
    await queue
      .getByText("دریافت وضعیت تازه ممکن نشد", { exact: true })
      .waitFor();
    assert.equal(
      await queue.locator(".execution-active.is-running").count(),
      0,
      "Stale data must not look like a confirmed active execution",
    );
    failQueue = false;
    offline = true;
    await queue
      .getByRole("button", { name: "بازخوانی صف اجراها", exact: true })
      .click();
    await queue
      .getByText("worker پاسخ تازه‌ای ندارد", { exact: true })
      .waitFor();
    assert.equal(
      await queue.locator(".execution-active.is-running").count(),
      0,
    );
    await queue
      .getByText("اجرای صف به run_api_worker نیاز دارد.", { exact: false })
      .waitFor();
    assert.equal(posts, 0);
    offline = false;
    await queue
      .getByRole("button", { name: "بازخوانی صف اجراها", exact: true })
      .click();
    await queue.getByText("فعال روی سرور", { exact: true }).waitFor();
    const clear = queue.getByRole("button", {
      name: "پاک‌کردن همهٔ صف انتظار",
      exact: true,
    });
    await clear.click();
    const confirmation = queue.getByRole("region", {
      name: "تأیید پاک‌کردن صف",
      exact: true,
    });
    await confirmation
      .getByRole("button", { name: "انصراف", exact: true })
      .click();
    assert.equal(clears.length, 0, "Dismissal never mutates the queue");
    await clear.click();
    const confirm = confirmation.getByRole("button", {
      name: "تأیید پاک‌کردن صف",
      exact: true,
    });
    await confirm.evaluate((button) => {
      button.click();
      button.click();
    });
    await confirmation.getByRole("alert").waitFor();
    assert.equal(clears.length, 1, "Duplicate clicks are guarded");
    await confirm.click();
    await confirmation.waitFor({ state: "detached" });
    await page.waitForFunction(
      () => document.querySelectorAll(".execution-waiting-row").length === 1,
    );
    assert.deepEqual(
      clears[0],
      clears[1],
      "Retry reuses the cutoff; new queued jobs survive",
    );
    assert(!page.url().includes("offset="), "Clear resets queue paging");
    await queue.getByText("فعال روی سرور", { exact: true }).waitFor();
    assert.equal(
      await queue.locator(".execution-active.is-running").count(),
      1,
      "Active execution is unaffected",
    );
    assert.deepEqual(errors, []);
    console.log(
      "PASS: global active owner differs from selected queued run; cross-day active visibility; FIFO paging/filter; selecting runs; ten-second polling; offline worker explanation; read-only navigation; safe clear confirmation, retry cutoff and double-click guard; responsive.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
