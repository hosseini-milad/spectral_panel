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

const root = `/api/v1/days/${day.day}/schematic/`;
const statusUrl = root + "jobs/" + jobId + "/";
const result = {
  kind: "day",
  layout: "global",
  day: day.day,
  inventory_snapshot_id: snapshot,
  hierarchy_run_id: "hierarchy-test",
  representative_run_id: "daily-test",
  coverage_status: "partial",
  generated_at: day.updated_at,
  metrics: {
    input_components: 6,
    meta_components: 4,
    daily_representatives: 5,
    candidate_nodes: 10,
    unresolved_candidates: 0,
    component_similarity_edges: 2,
    representative_similarity_edges: 1,
    membership_links: 11,
    components_with_daily_representatives: 5,
    isolated_input_components: 3,
    radius_coverage: null,
  },
  image_url: statusUrl + "files/png/",
  png_download_url: statusUrl + "files/png/?download=true",
  svg_download_url: statusUrl + "files/svg/?download=true",
};
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
    });
    page.setDefaultTimeout(12000);
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    let posts = 0,
      missing = false,
      mismatch = false;
    await page.route("**/api/v1/days/**", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === root) {
        posts++;
        assert.equal(route.request().method(), "POST");
        assert(route.request().headers()["idempotency-key"]);
        assert.deepEqual(route.request().postDataJSON(), {
          snapshot_id: snapshot,
        });
        if (missing)
          return route.fulfill({
            status: 409,
            json: { code: "daily_representatives_unavailable" },
          });
        return route.fulfill({
          status: 202,
          json: {
            job: {
              id: jobId,
              status: "queued",
              status_url: statusUrl,
              result: null,
            },
            created: true,
          },
        });
      }
      if (url.pathname === statusUrl)
        return route.fulfill({
          json: {
            id: jobId,
            status: "succeeded",
            status_url: statusUrl,
            result: { ...result, kind: mismatch ? "chunk" : "day" },
          },
        });
      if (url.pathname.startsWith(statusUrl + "files/")) {
        const ext = url.pathname.includes("svg") ? "svg" : "png";
        return route.fulfill({
          body: await fs.readFile(
            path.join(__dirname, "fixtures", `daily-schematic.${ext}`),
          ),
          contentType: ext === "png" ? "image/png" : "image/svg+xml",
          headers: url.searchParams.has("download")
            ? { "Content-Disposition": `attachment; filename="day.${ext}"` }
            : {},
        });
      }
      if (url.pathname.endsWith("/chunks/"))
        return route.fulfill({
          json: {
            day: day.day,
            snapshot_id: snapshot,
            count: 0,
            next: null,
            previous: null,
            results: [],
          },
        });
      if (url.pathname === `/api/v1/days/${day.day}/`)
        return route.fulfill({ json: day });
      return route.fulfill({
        json: { count: 1, next: null, previous: null, results: [day] },
      });
    });
    await page.goto(base + "/#/days");
    await page.getByRole("tab", { name: "گزارش روز", exact: true }).click();
    assert.equal(posts, 0, "daily image must be on demand");
    await page
      .getByRole("button", { name: "نمایش تصویر شماتیک", exact: true })
      .click();
    const popup = page.getByRole("dialog");
    await popup.waitFor();
    await page.waitForFunction(
      () => document.querySelector(".chunk-schematic-image")?.naturalWidth > 0,
    );
    assert.match(await popup.innerText(), /hierarchy-test/);
    assert.match(await popup.innerText(), /daily-test/);
    assert.match(await popup.innerText(), /رابطهٔ عضویت/);
    assert.match(await popup.innerText(), /جزئی/);
    assert.equal(await popup.locator(".chunk-schematic-image").count(), 1);
    for (const ext of ["PNG", "SVG"]) {
      const waiting = page.waitForEvent("download");
      await popup
        .getByRole("link", { name: "ذخیرهٔ " + ext, exact: true })
        .click();
      const file = await waiting;
      assert((await fs.readFile(await file.path())).length > 100);
    }
    if (process.env.TEST_OUTPUT_DIR)
      await page.screenshot({
        path: process.env.TEST_OUTPUT_DIR + "/daily-popup.png",
        fullPage: true,
      });
    await page.keyboard.press("Escape");
    await popup.waitFor({ state: "hidden" });
    await page
      .getByRole("button", { name: "مشاهدهٔ تصویر", exact: true })
      .click();
    await popup.waitFor();
    assert.equal(posts, 1);
    await page.setViewportSize({ width: 390, height: 844 });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    mismatch = true;
    await popup
      .getByRole("button", { name: "تولید دوباره", exact: true })
      .click();
    await popup.getByRole("alert").waitFor();
    assert.equal(await popup.locator(".chunk-schematic-image").count(), 0);
    mismatch = false;
    missing = true;
    await popup
      .getByRole("button", { name: "تولید دوباره", exact: true })
      .click();
    await popup.getByRole("alert").filter({ hasText: "روزانه" }).waitFor();
    assert.deepEqual(errors, []);
    console.log(
      "PASS: daily on-demand scope, popup, daily metrics, partial coverage, source versions, PNG/SVG, Escape/reopen, mobile, scope guard and missing prerequisites.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
