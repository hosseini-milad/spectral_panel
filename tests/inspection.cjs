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

const reportId = "c5724874-c7cf-45ab-a4a6-9c697a1096d1";
const root = `/api/v1/days/${day.day}/inspection/`;
const baseReport = root + "reports/" + reportId + "/";
const jobUrl = root + "jobs/" + jobId + "/";
const hId = "hierarchy-version-1";
const stats = (attack, normal, daily = 0, missing = 0) => ({
  labels: { attack, normal, unknown: 0 },
  composition:
    attack && normal ? "mixed" : attack ? "attack_only" : "normal_only",
  observation_count: attack + normal,
  layer1_representatives: attack && normal ? 2 : 1,
  daily_representatives: daily,
  missing_raw_records: missing,
  label_conflicts: 0,
});
const report = {
  ...stats(12, 24, 1, 1),
  id: reportId,
  day: day.day,
  schema_version: "day_inspection_v1",
  hierarchy_run_id: hId,
  daily_representative_run_id: "daily-version-1",
  inventory_snapshot_id: snapshot,
  generated_at: day.updated_at,
  coverage_status: "partial",
  meta_count: 2,
  component_count: 3,
  attack_meta_count: 1,
  normal_meta_count: 2,
  unknown_meta_count: 0,
  source_signature: "a".repeat(64),
  metas_url: baseReport + "metas/",
  limitations: [],
};
const metas = [
  {
    ...stats(12, 12, 1, 1),
    meta_id: "meta-attack-mixed",
    meta_index: 0,
    component_count: 2,
    source_chunks: [0, 1],
    density: 1,
    internal_edges: 1,
  },
  {
    ...stats(0, 12),
    meta_id: "meta-normal",
    meta_index: 1,
    component_count: 1,
    source_chunks: [1],
    density: 0,
    internal_edges: 0,
  },
];
const components = [
  {
    ...stats(12, 0, 1, 1),
    meta_id: metas[0].meta_id,
    component_id: "component-attack",
    chunk_index: 0,
    component_index: 0,
  },
  {
    ...stats(0, 12),
    meta_id: metas[0].meta_id,
    component_id: "component-normal",
    chunk_index: 1,
    component_index: 0,
  },
  {
    ...stats(0, 12),
    meta_id: metas[1].meta_id,
    component_id: "component-other",
    chunk_index: 1,
    component_index: 1,
  },
];
const rows = components.flatMap((component, k) =>
  Array.from({ length: 12 }, (_, i) => {
    const missing = k === 0 && i === 11,
      attack = k === 0;
    const raw = {
      src_ip: missing ? null : `192.0.2.${i + 1}`,
      dst_ip: missing ? null : "198.51.100.5",
      src_port: missing ? null : 12345,
      dst_port: missing ? null : 443,
      protocol: missing ? null : "tcp",
      label: missing ? null : attack ? "DDoS" : "BENIGN",
      label_binary: missing ? null : attack ? 1 : 0,
      bytes: missing ? null : 10000,
      duration_s: missing ? null : 5,
    };
    const normalized = {
      ...raw,
      src_ip: 0.25,
      dst_ip: 0.5,
      src_port: 0.1,
      dst_port: 0.2,
      label: attack ? 1 : 0,
      bytes: 0.7,
    };
    return {
      position: i,
      observation_id: `obs-${k}-${i}`,
      original_id: `raw-${k}-${i}`,
      meta_id: component.meta_id,
      component_id: component.component_id,
      chunk_index: component.chunk_index,
      label: attack ? "attack" : "normal",
      label_origin: missing ? "candidate" : "raw",
      raw_available: !missing,
      normalized_available: true,
      layer1_representative: i === 0,
      daily_representative: k === 0 && i === 0,
      raw_summary: raw,
      raw_fields: raw,
      normalized_fields: normalized,
      candidate_fields: normalized,
      omitted_fields: { raw: [], normalized: [], candidate: [] },
      source_file_basename: missing ? null : "flows.parquet",
      row_index: i,
    };
  }),
);
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
    let created = false,
      finished = false,
      abortFirst = true,
      posts = 0;
    const keys = [],
      polls = [];
    await page.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === "/api/v1/days/")
        return route.fulfill({
          json: { count: 1, next: null, previous: null, results: [day] },
        });
      if (url.pathname === `/api/v1/days/${day.day}/`)
        return route.fulfill({ json: day });
      if (url.pathname === root && route.request().method() === "POST") {
        posts++;
        keys.push(route.request().headers()["idempotency-key"]);
        assert.deepEqual(route.request().postDataJSON(), {
          snapshot_id: snapshot,
          hierarchy_run_id: hId,
        });
        if (abortFirst) {
          abortFirst = false;
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
              worker: { online: false, busy: false },
              queue_position: 1,
              status_url: jobUrl,
            },
          },
        });
      }
      if (url.pathname === root)
        return route.fulfill({
          json: {
            active_hierarchy_run_id: hId,
            available_hierarchy: true,
            report: created ? report : null,
            stale: false,
            build_required: !created,
          },
        });
      if (url.pathname === jobUrl) {
        polls.push(Date.now());
        if (finished) created = true;
        return route.fulfill({
          json: {
            id: jobId,
            report_id: reportId,
            status: finished ? "succeeded" : "queued",
            worker: { online: false, busy: false },
            queue_position: 1,
            status_url: jobUrl,
          },
        });
      }
      if (url.pathname === baseReport) return route.fulfill({ json: report });
      const label = url.searchParams.get("label") ?? "all",
        offset = Number(url.searchParams.get("offset") ?? 0),
        limit = Number(url.searchParams.get("limit") ?? 20);
      const pageOf = (list) => ({
        count: list.length,
        next: offset + limit < list.length ? "next" : null,
        previous: offset ? "previous" : null,
        results: list.slice(offset, offset + limit),
      });
      const matches = (row) =>
        label === "all" ||
        (row.labels ? row.labels[label] > 0 : row.label === label);
      if (url.pathname === baseReport + "metas/")
        return route.fulfill({ json: pageOf(metas.filter(matches)) });
      const match = url.pathname.match(
        /\/metas\/([^/]+)\/components\/(?:([^/]+)\/observations\/(?:([^/]+)\/)?)?$/,
      );
      if (match) {
        const [, meta, component, observation] = match;
        if (!component)
          return route.fulfill({
            json: pageOf(
              components.filter((c) => c.meta_id === meta && matches(c)),
            ),
          });
        let selected = rows.filter(
          (r) => r.meta_id === meta && r.component_id === component,
        );
        if (observation) {
          const found = selected.find((r) => r.observation_id === observation);
          return route.fulfill({
            status: found ? 200 : 404,
            json: found ?? { code: "not_found" },
          });
        }
        selected = selected.filter(matches);
        const ip = url.searchParams.get("ip"),
          rep = url.searchParams.get("representative");
        if (ip)
          selected = selected.filter(
            (r) => r.raw_summary.src_ip === ip || r.raw_summary.dst_ip === ip,
          );
        if (rep && rep !== "all")
          selected = selected.filter((r) => r[rep + "_representative"]);
        return route.fulfill({ json: pageOf(selected) });
      }
      throw new Error("Unexpected path " + url.pathname);
    });
    await page.goto(base + "/#/visualizations?day=" + day.day);
    const build = page.getByRole("button", {
      name: "ساخت گزارش جزئیات",
      exact: true,
    });
    await page.waitForFunction(
      () =>
        !Array.from(document.querySelectorAll("button")).find(
          (b) => b.textContent === "ساخت گزارش جزئیات",
        )?.disabled,
    );
    await build.evaluate((b) => {
      b.click();
      b.click();
    });
    await page
      .getByRole("alert")
      .filter({ hasText: "ارتباط قطع شد" })
      .waitFor();
    assert.equal(posts, 1);
    await page
      .getByRole("button", { name: "تلاش دوباره", exact: true })
      .click();
    await page
      .getByRole("status")
      .filter({ hasText: "worker گزارش فعال نیست" })
      .waitFor();
    assert.equal(keys[0], keys[1]);
    const count = polls.length;
    await page.waitForTimeout(2200);
    assert.equal(polls.length, count);
    finished = true;
    await page
      .getByRole("heading", { name: "۱. فرامولفه‌های روزانه", exact: true })
      .waitFor();
    assert(polls.at(-1) - polls.at(-2) >= 9000);
    assert.equal(await page.locator(".hi-summary > div").count(), 6);
    await page
      .getByLabel("فیلتر برچسب فرامولفه", { exact: true })
      .selectOption("attack");
    await page.waitForFunction(
      () =>
        document.querySelectorAll(".hi-level")[0]?.querySelectorAll("tbody tr")
          .length === 1,
    );
    assert.match(await page.locator(".hi-level").first().innerText(), /مختلط/);
    await page
      .getByRole("button", { name: "مشاهده مولفه‌های فرامولفه 0", exact: true })
      .click();
    await page
      .getByRole("button", {
        name: "مشاهده داده‌های مولفه component-attack",
        exact: true,
      })
      .click();
    await page
      .getByRole("button", { name: "جزئیات داده اصلی obs-0-0", exact: true })
      .click();
    await page.getByRole("heading", { name: /۴. جزئیات دادهٔ اصلی/ }).waitFor();
    const flow = page.locator(".hi-flow");
    assert.match(await flow.innerText(), /192.0.2.1/);
    assert.match(await flow.innerText(), /DDoS/);
    assert.match(await flow.innerText(), /0.25/);
    assert.match(await flow.innerText(), /raw-0-0/);
    await page.reload();
    await page.locator(".hi-flow").waitFor();
    await page
      .locator(".hi-flow")
      .getByText("raw-0-0", { exact: true })
      .waitFor();
    assert.equal(
      posts,
      2,
      "reload must preserve deep link without resetting to meta list or submitting",
    );
    await page
      .locator(".hi-level")
      .filter({
        has: page.getByRole("heading", {
          name: "۳. مشاهدات مولفه و ارتباط با دادهٔ اصلی",
          exact: true,
        }),
      })
      .getByRole("button", { name: "بعدی", exact: true })
      .click();
    await page
      .getByRole("button", { name: "جزئیات داده اصلی obs-0-11", exact: true })
      .click();
    await page
      .getByText(
        "رکورد اصلی هنگام ساخت این گزارش موجود نبود؛ مقادیر اصلی از دادهٔ نرمال‌شده بازسازی نشده‌اند.",
        { exact: true },
      )
      .waitFor();
    await page.getByLabel("جستجوی IP اصلی", { exact: true }).fill("192.0.2.3");
    await page
      .locator(".hi-observation-filters")
      .getByRole("button", { name: "جستجو", exact: true })
      .click();
    await page
      .getByRole("button", { name: "جزئیات داده اصلی obs-0-2", exact: true })
      .waitFor();
    await page
      .getByLabel("فیلتر نماینده", { exact: true })
      .selectOption("daily");
    await page
      .getByText("مشاهده‌ای با این فیلتر وجود ندارد.", { exact: true })
      .waitFor();
    await page
      .getByLabel("فیلتر برچسب مولفه", { exact: true })
      .selectOption("normal");
    await page
      .getByRole("button", {
        name: "مشاهده داده‌های مولفه component-normal",
        exact: true,
      })
      .click();
    await page
      .getByRole("button", { name: "جزئیات داده اصلی obs-1-0", exact: true })
      .click();
    await page
      .locator(".hi-flow")
      .getByText("BENIGN", { exact: true })
      .waitFor();
    if (process.env.TEST_OUTPUT_DIR)
      await page.screenshot({
        path: process.env.TEST_OUTPUT_DIR + "/inspection-desktop.png",
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
        path: process.env.TEST_OUTPUT_DIR + "/inspection-mobile.png",
        fullPage: true,
      });
    assert.deepEqual(errors, []);
    console.log(
      "PASS: explicit durable report, retry key, 10-second polling, attack/mixed/normal hierarchy filters, meta→component→original flow, exact raw/normalized separation, missing raw, pagination/IP/representative filters, pinned deep-link reload, mobile and no browser errors.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
