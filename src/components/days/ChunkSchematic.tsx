import { useEffect, useRef, useState } from "react";
import { Image, Download, RotateCw, X } from "lucide-react";
import {
  apiPath,
  createSchematic,
  createDailySchematic,
  type SchematicResult,
  type DailySchematicResult,
  getJSON,
  type InventoryDay,
  type InventoryChunk,
  type SchematicJob,
  displayNumber as number,
  observationTime,
} from "../../api/days";

// One client request key per pending submission, including StrictMode remounts.
// These entries contain no node data; retries and reopening a chunk share its job.
const requests = new Map<string, { key: string; job?: SchematicJob }>();
const active = (job: SchematicJob) =>
  job.status === "queued" || job.status === "running";

function metricRows(
  result: SchematicResult | DailySchematicResult,
): ReadonlyArray<readonly [string, number | null]> {
  if (result.kind === "day")
    return [
      ["مولفهٔ ورودی", result.metrics.input_components],
      ["فرامولفه", result.metrics.meta_components],
      ["نمایندهٔ روزانه", result.metrics.daily_representatives],
      ["مشاهدهٔ کاندید", result.metrics.candidate_nodes],
      ["یال شباهت مولفه‌ها", result.metrics.component_similarity_edges],
      ["یال شباهت نماینده‌ها", result.metrics.representative_similarity_edges],
      ["رابطهٔ عضویت", result.metrics.membership_links],
      [
        "مولفهٔ دارای نمایندهٔ روزانه",
        result.metrics.components_with_daily_representatives,
      ],
      ["مولفهٔ ورودی منزوی", result.metrics.isolated_input_components],
      ["انتساب ناموجود", result.metrics.unresolved_candidates],
      ["پوشش شعاع (۰ تا ۱)", result.metrics.radius_coverage],
    ];
  return [
    ["گره", result.metrics.nodes],
    ["یال", result.metrics.edges],
    ["نماینده", result.metrics.representatives],
    ["مولفه", result.metrics.components],
    ["مولفهٔ دارای نماینده", result.metrics.represented_components],
    ["گره منزوی", result.metrics.isolated_nodes],
    ["میانگین درجه", result.metrics.mean_degree],
    ["تراکم (۰ تا ۱)", result.metrics.density],
    ["کاهش نسبت به گراف (٪)", result.metrics.node_reduction_percent],
  ];
}

export default function ChunkSchematic({
  day,
  chunk,
}: {
  day: InventoryDay;
  chunk?: InventoryChunk;
}) {
  const identity = `${day.day}:${chunk?.chunk_index ?? "day"}:${day.snapshot_id}`;
  const scopePath = chunk
    ? `days/${day.day}/chunks/${chunk.chunk_index}/schematic/`
    : `days/${day.day}/schematic/`;
  const scopeTitle = chunk
    ? `تصویر شماتیک چانک ${number(chunk.chunk_index)}`
    : "تصویر شماتیک روز";
  const [job, setJob] = useState<SchematicJob | null>(
    () => requests.get(identity)?.job ?? null,
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [imageError, setImageError] = useState(false);
  const [pollAttempt, setPollAttempt] = useState(0);
  const [open, setOpen] = useState(false);
  const [visible, setVisible] = useState(!document.hidden);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const change = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", change);
    return () => document.removeEventListener("visibilitychange", change);
  }, []);
  useEffect(() => {
    const element = dialog.current;
    if (open && !element?.open) element?.showModal();
    if (!open && element?.open) element.close();
    const previous = document.body.style.overflow;
    if (open) document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);
  const submission = useRef<AbortController | null>(null);
  const ready = !chunk || Boolean(chunk.graph && chunk.representatives > 0);
  useEffect(() => () => submission.current?.abort(), []);

  async function generate(fresh = false) {
    if (submission.current) return;
    const controller = new AbortController();
    submission.current = controller;
    if (fresh || !requests.has(identity)) {
      if (requests.size >= 100) requests.delete(requests.keys().next().value!);
      requests.set(identity, { key: crypto.randomUUID() });
      setJob(null);
    }
    const record = requests.get(identity)!;
    setBusy(true);
    setError("");
    setImageError(false);
    try {
      const payload = await (chunk
        ? createSchematic(
            day.day,
            chunk.chunk_index,
            day.snapshot_id,
            record.key,
            controller.signal,
          )
        : createDailySchematic(
            day.day,
            day.snapshot_id,
            record.key,
            controller.signal,
          ));
      if (!controller.signal.aborted) {
        record.job = payload.job;
        setJob(payload.job);
      }
    } catch (cause) {
      if (!controller.signal.aborted) setError((cause as Error).message);
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      if (submission.current === controller) submission.current = null;
    }
  }
  const jobId = job?.id;
  const jobStatus = job?.status;
  useEffect(() => {
    if (
      !open ||
      !visible ||
      !jobId ||
      (jobStatus !== "queued" && jobStatus !== "running")
    )
      return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let queuedPolls = 0;
    const poll = async () => {
      try {
        const next = await getJSON<SchematicJob>(
          apiPath(`${scopePath}jobs/${jobId}/`),
          controller.signal,
        );
        if (controller.signal.aborted) return;
        const entry = requests.get(identity);
        if (entry) entry.job = next;
        setJob(next);
        setError("");
        if (active(next)) {
          queuedPolls = next.status === "queued" ? queuedPolls + 1 : 0;
          const seconds =
            next.poll_after_seconds ??
            (next.status === "queued" ? Math.min(15, 3 + queuedPolls * 2) : 2);
          timer = setTimeout(poll, Math.max(2, Math.min(30, seconds)) * 1000);
        }
      } catch (cause) {
        if (!controller.signal.aborted) setError((cause as Error).message);
      }
    };
    timer = setTimeout(poll, 500);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [
    jobId,
    jobStatus,
    identity,
    day.day,
    scopePath,
    pollAttempt,
    open,
    visible,
  ]);

  const result = job?.result;
  const matches =
    result &&
    result.day === day.day &&
    (chunk
      ? result.kind !== "day" && result.chunk_index === chunk.chunk_index
      : result.kind === "day") &&
    job?.status === "succeeded" &&
    result.inventory_snapshot_id === day.snapshot_id &&
    result.layout === "global";
  return (
    <section className="chunk-schematic" aria-label={scopeTitle}>
      <div className="report-heading">
        <div>
          <h3>
            <Image size={18} />
            {chunk
              ? "گراف و نماینده‌های انتخاب‌شده"
              : "مولفه‌ها، فرامولفه‌ها و نماینده‌های روزانه"}
          </h3>
          <p>
            {chunk
              ? "همهٔ گره‌های گراف ذخیره‌شده و نماینده‌ها در یک نمودار مشترک؛ نماینده‌ها با حاشیهٔ برجسته مشخص‌اند."
              : "مولفه‌ها، فرامولفه‌ها و مشاهدات نماینده در یک نمودار؛ خطوط عضویت از یال‌های شباهت جدا هستند."}
          </p>
        </div>
        <button
          className="days-button"
          disabled={!ready || busy}
          onClick={() => {
            setOpen(true);
            if (!job) void generate(false);
          }}
        >
          <RotateCw size={15} />
          {busy
            ? "در حال ثبت درخواست…"
            : job && active(job)
              ? "نمایش وضعیت تصویر"
              : job?.status === "succeeded"
                ? "مشاهدهٔ تصویر"
                : "نمایش تصویر شماتیک"}
        </button>
      </div>
      {!ready && (
        <p className="chunk-detail-note">
          برای تولید تصویر، گراف و نماینده‌های انتخاب‌شده باید در سرور موجود
          باشند.
        </p>
      )}
      <dialog
        ref={dialog}
        className="chunk-schematic-dialog"
        aria-labelledby={`schematic-title-${day.day}-${chunk?.chunk_index ?? "day"}`}
        onCancel={() => setOpen(false)}
        onClose={() => setOpen(false)}
        onClick={(event) => {
          if (event.target !== event.currentTarget) return;
          const rect = event.currentTarget.getBoundingClientRect();
          if (
            event.clientX < rect.left ||
            event.clientX > rect.right ||
            event.clientY < rect.top ||
            event.clientY > rect.bottom
          )
            setOpen(false);
        }}
      >
        <header className="chunk-schematic-dialog-heading">
          <h2 id={`schematic-title-${day.day}-${chunk?.chunk_index ?? "day"}`}>
            {scopeTitle} · {day.day}
          </h2>
          <button
            className="icon-button"
            aria-label="بستن تصویر شماتیک"
            onClick={() => setOpen(false)}
          >
            <X size={20} />
          </button>
        </header>
        {busy && (
          <p className="chunk-detail-note" role="status">
            در حال ثبت درخواست تصویر…
          </p>
        )}
        {job && active(job) && (
          <p className="chunk-detail-note" role="status">
            {job.status === "queued"
              ? job.worker?.online === false
                ? "درخواست در صف است؛ سرویس رسم فعال نیست یا ارتباط آن برقرار نیست. هنوز رسم شروع نشده است."
                : "درخواست ثبت شد و در صف رسم است. هنوز رسم شروع نشده است."
              : "در حال محاسبهٔ چیدمان و رسم تصویر…"}{" "}
            {job.queue_position != null &&
              `جایگاه در صف: ${number(job.queue_position)}. `}
            {job.queued_seconds != null &&
              `زمان انتظار: ${number(job.queued_seconds)} ثانیه. `}
            {job.status === "running" &&
              job.running_seconds != null &&
              `زمان سپری‌شدهٔ رسم: ${number(job.running_seconds)} ثانیه. `}
            درصد پیشرفت قابل محاسبه نیست؛ بستن پنجره اجرای سرور را لغو نمی‌کند.
            <button
              className="days-text-button"
              onClick={() => setPollAttempt((value) => value + 1)}
            >
              بررسی وضعیت
            </button>
          </p>
        )}
        {error && (
          <p className="chunk-error" role="alert">
            {error}
            <button
              className="days-text-button"
              onClick={() => {
                if (job && active(job)) {
                  setError("");
                  setPollAttempt((value) => value + 1);
                } else void generate(false);
              }}
            >
              تلاش دوباره
            </button>
          </p>
        )}
        {job && ["failed", "interrupted", "cancelled"].includes(job.status) && (
          <p className="chunk-error" role="alert">
            {job.error?.code === "source_changed" ||
            job.error?.code === "inventory_changed"
              ? "داده‌های مبدأ تغییر کرده‌اند؛ روز را دوباره باز کنید و تصویر تازه بسازید."
              : "تولید تصویر انجام نشد؛ وجود و سازگاری گراف و نماینده‌ها را بررسی کنید و دوباره درخواست بدهید."}
          </p>
        )}
        {job?.status === "succeeded" && !matches && (
          <p className="chunk-error" role="alert">
            نتیجه با روز، چانک یا نسخهٔ فعلی تطابق ندارد؛ تصویر نمایش داده نشد.
          </p>
        )}
        {matches && (
          <>
            <a
              href={result.image_url}
              target="_blank"
              rel="noreferrer"
              aria-label="باز کردن تصویر در اندازهٔ اصلی"
            >
              <img
                className="chunk-schematic-image"
                src={result.image_url}
                alt={
                  result.kind === "day"
                    ? `شماتیک مولفه‌ها، فرامولفه‌ها و ${number(result.metrics.daily_representatives)} نمایندهٔ روز ${day.day}`
                    : `گراف چانک ${number(chunk?.chunk_index)} در ${day.day} با ${number(result.metrics.representatives)} نمایندهٔ برجسته`
                }
                onError={() => setImageError(true)}
                onLoad={() => setImageError(false)}
              />
            </a>
            {imageError && (
              <p className="chunk-error" role="alert">
                دریافت فایل تصویر ممکن نشد؛ می‌توانید از پیوند دانلود استفاده
                کنید.
              </p>
            )}
            <div className="table-controls">
              <a className="days-button" href={result.png_download_url}>
                <Download size={15} />
                ذخیرهٔ PNG
              </a>
              <a className="days-button" href={result.svg_download_url}>
                <Download size={15} />
                ذخیرهٔ SVG
              </a>
            </div>
            <dl className="chunk-metrics">
              {metricRows(result).map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>
                    {label === "تراکم (۰ تا ۱)"
                      ? new Intl.NumberFormat("fa-IR", {
                          maximumSignificantDigits: 4,
                        }).format(value ?? 0)
                      : number(value)}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="chunk-detail-note">
              تولید: {observationTime(result.generated_at)} · چیدمان شماتیک
              سراسری است.{" "}
              {result.kind === "day"
                ? "دایره: مولفه؛ لوزی: فرامولفه؛ مثلث: نمایندهٔ روزانه. خط‌چین و نقطه‌چین رابطهٔ عضویت هستند، نه شباهت. رنگ‌ها عضویت گروهی‌اند و ممکن است تکرار شوند."
                : "مولفه‌های جدا به هم وصل نشده‌اند. رنگ‌ها برچسب ذخیره‌شده‌اند، نه پیش‌بینی حمله."}{" "}
              پوشش عضویت و شعاع، دقت تشخیص حمله نیستند.
            </p>
            {result.kind === "day" && (
              <p className="chunk-detail-note">
                نسخهٔ سلسله‌مراتب: <bdi>{result.hierarchy_run_id}</bdi> · نسخهٔ
                نماینده‌های روزانه: <bdi>{result.representative_run_id}</bdi> ·
                پوشش روز:{" "}
                {result.coverage_status === "complete"
                  ? "کامل"
                  : result.coverage_status === "partial"
                    ? "جزئی"
                    : "تأییدنشده"}
                . این تصویر مرحلهٔ علمی تازه‌ای نمی‌سازد.
              </p>
            )}
            {result.kind !== "day" &&
              result.metrics.unknown_label_nodes > 0 && (
                <p className="chunk-detail-note">
                  {number(result.metrics.unknown_label_nodes)} گره برچسب معتبر
                  ندارند و خاکستری نمایش داده می‌شوند.
                </p>
              )}
          </>
        )}
        {job && !active(job) && (
          <button
            className="days-button"
            disabled={busy}
            onClick={() => void generate(true)}
          >
            <RotateCw size={15} />
            تولید دوباره
          </button>
        )}
      </dialog>
    </section>
  );
}
