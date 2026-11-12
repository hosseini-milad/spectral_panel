import { useEffect, useRef, useState } from "react";
import { Image, Download, RotateCw } from "lucide-react";
import {
  apiPath,
  createSchematic,
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

export default function ChunkSchematic({
  day,
  chunk,
}: {
  day: InventoryDay;
  chunk: InventoryChunk;
}) {
  const identity = `${day.day}:${chunk.chunk_index}:${day.snapshot_id}`;
  const [job, setJob] = useState<SchematicJob | null>(
    () => requests.get(identity)?.job ?? null,
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [imageError, setImageError] = useState(false);
  const [pollAttempt, setPollAttempt] = useState(0);
  const submission = useRef<AbortController | null>(null);
  const ready = Boolean(chunk.graph && chunk.representatives > 0);
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
      const payload = await createSchematic(
        day.day,
        chunk.chunk_index,
        day.snapshot_id,
        record.key,
        controller.signal,
      );
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
    if (!jobId || (jobStatus !== "queued" && jobStatus !== "running")) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await getJSON<SchematicJob>(
          apiPath(
            `days/${day.day}/chunks/${chunk.chunk_index}/schematic/jobs/${jobId}/`,
          ),
          controller.signal,
        );
        if (controller.signal.aborted) return;
        const entry = requests.get(identity);
        if (entry) entry.job = next;
        setJob(next);
        setError("");
        if (active(next)) timer = setTimeout(poll, 1500);
      } catch (cause) {
        if (!controller.signal.aborted) setError((cause as Error).message);
      }
    };
    timer = setTimeout(poll, 500);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [jobId, jobStatus, identity, day.day, chunk.chunk_index, pollAttempt]);

  const result = job?.result;
  const matches =
    result &&
    result.day === day.day &&
    result.chunk_index === chunk.chunk_index &&
    job?.status === "succeeded" &&
    result.inventory_snapshot_id === day.snapshot_id &&
    result.layout === "global";
  return (
    <section
      className="chunk-schematic"
      aria-label={`تصویر شماتیک چانک ${number(chunk.chunk_index)}`}
    >
      <div className="report-heading">
        <div>
          <h3>
            <Image size={18} />
            گراف و نماینده‌های انتخاب‌شده
          </h3>
          <p>
            همهٔ گره‌های گراف ذخیره‌شده و نماینده‌ها در یک نمودار مشترک؛
            نماینده‌ها با حاشیهٔ برجسته مشخص‌اند.
          </p>
        </div>
        <button
          className="days-button"
          disabled={!ready || busy || Boolean(job && active(job))}
          onClick={() => void generate(Boolean(job && !active(job)))}
        >
          <RotateCw size={15} />
          {busy
            ? "در حال ثبت درخواست…"
            : job && active(job)
              ? "در حال تولید تصویر…"
              : job
                ? "تولید دوباره"
                : "نمایش تصویر شماتیک"}
        </button>
      </div>
      {!ready && (
        <p className="chunk-detail-note">
          برای تولید تصویر، گراف و نماینده‌های انتخاب‌شده باید در سرور موجود
          باشند.
        </p>
      )}
      {job && active(job) && (
        <p className="chunk-detail-note" role="status">
          {job.status === "queued"
            ? "درخواست ثبت شد و در صف رسم است."
            : "در حال محاسبهٔ چیدمان و رسم تصویر…"}{" "}
          درصد پیشرفت قابل محاسبه نیست؛ خروج از این بخش، اجرای سرور را لغو
          نمی‌کند.
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
              alt={`گراف چانک ${number(chunk.chunk_index)} در ${day.day} با ${number(result.metrics.representatives)} نمایندهٔ برجسته`}
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
            {(
              [
                ["گره", result.metrics.nodes],
                ["یال", result.metrics.edges],
                ["نماینده", result.metrics.representatives],
                ["مولفه", result.metrics.components],
                ["مولفهٔ دارای نماینده", result.metrics.represented_components],
                ["گره منزوی", result.metrics.isolated_nodes],
                ["میانگین درجه", result.metrics.mean_degree],
                ["تراکم (۰ تا ۱)", result.metrics.density],
                [
                  "کاهش نسبت به گراف (٪)",
                  result.metrics.node_reduction_percent,
                ],
              ] as const
            ).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>
                  {label === "تراکم (۰ تا ۱)"
                    ? new Intl.NumberFormat("fa-IR", {
                        maximumSignificantDigits: 4,
                      }).format(value)
                    : number(value)}
                </dd>
              </div>
            ))}
          </dl>
          <p className="chunk-detail-note">
            تولید: {observationTime(result.generated_at)} · چیدمان شماتیک سراسری
            است؛ مولفه‌های جدا به هم وصل نشده‌اند. رنگ‌ها برچسب ذخیره‌شده‌اند،
            نه پیش‌بینی حمله. مولفهٔ دارای نماینده، معیار پوشش عضویت است و دقت
            تشخیص نیست.
          </p>
          {result.metrics.unknown_label_nodes > 0 && (
            <p className="chunk-detail-note">
              {number(result.metrics.unknown_label_nodes)} گره برچسب معتبر
              ندارند و خاکستری نمایش داده می‌شوند.
            </p>
          )}
        </>
      )}
    </section>
  );
}
