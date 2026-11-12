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
const chunk = {
  day: day.day,
  snapshot_id: snapshot,
  chunk_index: 1,
  status: "complete",
  expected_raw_records: 100,
  normalized_records: 100,
  normalization_complete: true,
  candidate_records: 100,
  components: 2,
  representatives: 10,
  graph: {
    source_file: "clustered-day-2026-06-22-chunk-1",
    nodes: 100,
    edges: 98,
    component_status: "complete",
    component_count: 2,
  },
  updated_at: day.updated_at,
};
const root = `/api/v1/days/${day.day}/chunks/1/schematic/`;
const statusUrl = root + "jobs/" + jobId + "/";
const queued = {
  id: jobId,
  render_id: jobId,
  status: "queued",
  status_url: statusUrl,
  error: null,
  result: null,
  progress: { phase: "queued", percent: null },
};
const result = {
  schema_version: "chunk_schematic_global_v1",
  render_id: jobId,
  day: day.day,
  chunk_index: 1,
  inventory_snapshot_id: snapshot,
  source_signature: "a".repeat(64),
  component_revision: null,
  generated_at: day.updated_at,
  layout: "global",
  label_source: "graph_metadata.node_labels",
  metrics: {
    nodes: 100,
    edges: 98,
    representatives: 10,
    components: 2,
    represented_components: 1,
    isolated_nodes: 1,
    mean_degree: 1.96,
    density: 98 / 4950,
    node_reduction_percent: 90,
    normal_label_nodes: 50,
    attack_label_nodes: 50,
    unknown_label_nodes: 0,
  },
  image_url: statusUrl + "files/png/",
  png_download_url: statusUrl + "files/png/?download=true",
  svg_download_url: statusUrl + "files/svg/?download=true",
};
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
  page.on("pageerror", (e) => errors.push(e.message));
  let postCount = 0,
    pollCount = 0,
    mismatch = false,
    failJob = false;
  const keys = [];
  await page.context().route("**/api/v1/days/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === root && route.request().method() === "POST") {
      postCount++;
      keys.push(route.request().headers()["idempotency-key"]);
      assert.deepEqual(route.request().postDataJSON(), {
        snapshot_id: snapshot,
      });
      if (postCount === 1) return route.abort("failed"); // server accepted; client lost the response
      pollCount = 0;
      return route.fulfill({
        status: 202,
        json: { job: queued, created: postCount !== 2 },
      });
    }
    if (url.pathname === statusUrl) {
      pollCount++;
      if (pollCount === 1)
        return route.fulfill({
          json: {
            ...queued,
            status: "running",
            progress: { phase: "rendering", percent: null },
          },
        });
      return route.fulfill({
        json: failJob
          ? { ...queued, status: "failed", error: { code: "source_changed" } }
          : {
              ...queued,
              status: "succeeded",
              result: {
                ...result,
                inventory_snapshot_id: mismatch
                  ? "different-snapshot"
                  : snapshot,
              },
            },
      });
    }
    if (url.pathname.startsWith(statusUrl + "files/")) {
      const format = url.pathname.includes("/svg/") ? "svg" : "png";
      const bytes = await fs.readFile(
        path.join(__dirname, "fixtures", `schematic.${format}`),
      );
      return route.fulfill({
        body: bytes,
        contentType: format === "svg" ? "image/svg+xml" : "image/png",
        headers: url.searchParams.has("download")
          ? {
              "Content-Disposition": `attachment; filename="schematic.${format}"`,
            }
          : {},
      });
    }
    if (url.pathname.endsWith("/chunks/"))
      return route.fulfill({
        json: {
          day: day.day,
          snapshot_id: snapshot,
          count: 1,
          next: null,
          previous: null,
          results: [chunk],
        },
      });
    if (url.pathname === `/api/v1/days/${day.day}/`)
      return route.fulfill({ json: day });
    return route.fulfill({
      json: { count: 1, next: null, previous: null, results: [day] },
    });
  });
  await page.goto(base + "/#/days");
  await page.locator(".chunk-name").click();
  const panel = page.getByRole("region", { name: "تصویر شماتیک چانک ۱" });
  const generate = page.getByRole("button", {
    name: "نمایش تصویر شماتیک",
    exact: true,
  });
  await generate.waitFor();
  await generate.evaluate((button) => {
    button.click();
    button.click();
  });
  await page
    .getByRole("alert")
    .filter({ hasText: "ارتباط با سرور برقرار نشد" })
    .waitFor();
  assert.equal(postCount, 1);
  await page.getByRole("button", { name: "تلاش دوباره", exact: true }).click();
  await page
    .getByText("درخواست ثبت شد و در صف رسم است.", { exact: false })
    .waitFor();
  await page.locator(".chunk-schematic-image").waitFor();
  await page.waitForFunction(
    () => document.querySelector(".chunk-schematic-image")?.naturalWidth > 0,
  );
  assert.equal(postCount, 2);
  assert.equal(keys[0], keys[1]);
  assert.match(
    await page.locator(".chunk-schematic").innerText(),
    /میانگین درجه/,
  );
  assert.equal(await page.locator(".chunk-schematic-image").count(), 1);
  for (const extension of ["PNG", "SVG"]) {
    const downloadPromise = page.waitForEvent("download");
    await page
      .getByRole("link", { name: "ذخیرهٔ " + extension, exact: true })
      .click();
    const download = await downloadPromise;
    assert.match(
      download.suggestedFilename(),
      new RegExp("\\." + extension.toLowerCase() + "$"),
    );
    const content = await fs.readFile(await download.path());
    assert(content.length > 100);
    if (extension === "PNG") assert.equal(content[0], 137);
  }
  if (process.env.TEST_OUTPUT_DIR)
    await page.screenshot({
      path: process.env.TEST_OUTPUT_DIR + "/schematic-desktop.png",
      fullPage: true,
    });
  await page.setViewportSize({ width: 390, height: 844 });
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  );
  if (process.env.TEST_OUTPUT_DIR)
    await page.screenshot({
      path: process.env.TEST_OUTPUT_DIR + "/schematic-mobile.png",
      fullPage: true,
    });
  // Explicit new request creates a new key. A mismatched snapshot is never displayed.
  mismatch = true;
  await page.getByRole("button", { name: "تولید دوباره", exact: true }).click();
  await page
    .getByRole("alert")
    .filter({ hasText: "نتیجه با روز، چانک یا نسخهٔ فعلی تطابق ندارد" })
    .waitFor();
  assert.equal(await page.locator(".chunk-schematic-image").count(), 0);
  assert.notEqual(keys[1], keys[2]);
  mismatch = false;
  failJob = true;
  await page.getByRole("button", { name: "تولید دوباره", exact: true }).click();
  await page
    .getByRole("alert")
    .filter({ hasText: "داده‌های مبدأ تغییر کرده‌اند" })
    .waitFor();
  assert.equal(await page.locator(".chunk-schematic-image").count(), 0);
  assert.deepEqual(errors, []);
  await browser.close();
  console.log(
    "PASS: on-demand POST, double-click protection, retry key reuse, polling, one unified image, real PNG/SVG downloads, source-version guard, failed jobs, mobile layout.",
  );
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
