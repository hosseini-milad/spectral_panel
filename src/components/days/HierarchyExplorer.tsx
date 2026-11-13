import { useEffect, useRef, useState } from "react";
import {
  Database,
  Layers3,
  ChevronLeft,
  Search,
  AlertTriangle,
} from "lucide-react";
import {
  apiPath,
  getJSON,
  type InventoryDay,
  type Page,
  displayNumber as number,
} from "../../api/days";
import { useApi } from "../../hooks/useApi";
import {
  inspectionRoot,
  createInspection,
  labelNames,
  compositionNames,
  type InspectionContext,
  type InspectionReport,
  type InspectionMeta,
  type InspectionComponent,
  type InspectionObservation,
  type InspectionFlow,
  type InspectionJob,
  type GroupStats,
  type StoredValue,
} from "../../api/inspection";
import "./hierarchy-explorer.css";
export interface InspectionNavigation {
  chunkIndex?: number;
  reportId?: string;
  metaId?: string;
  componentId?: string;
  observationId?: string;
  jobId?: string;
}
const value = (v: StoredValue | undefined) =>
  v === null || v === undefined
    ? "—"
    : typeof v === "boolean"
      ? v
        ? "بله"
        : "خیر"
      : String(v);
const short = (v?: string) => (v ? `${v.slice(0, 8)}…` : "");
const fieldNames: Record<string, string> = {
  src_ip: "IP مبدأ",
  dst_ip: "IP مقصد",
  src_port: "پورت مبدأ",
  dst_port: "پورت مقصد",
  protocol: "پروتکل",
  label: "برچسب ذخیره‌شده",
  label_binary: "برچسب دودویی",
  label_multiclass: "برچسب چندکلاسه",
  source_label: "برچسب منبع",
  source_label_binary: "برچسب دودویی منبع",
  source_label_multiclass: "برچسب چندکلاسهٔ منبع",
  attack_type: "نوع حملهٔ ثبت‌شده",
  attack_category: "دستهٔ حملهٔ ثبت‌شده",
  bytes: "حجم (بایت)",
  packets: "تعداد بسته",
  duration_s: "مدت (ثانیه)",
  timestamp: "زمان رخداد ذخیره‌شده",
  flow_start: "شروع جریان",
  flow_end: "پایان جریان",
  window_start: "شروع بازه",
};
function Counts({ group }: { group: GroupStats }) {
  return (
    <span className="hi-counts">
      <span className="attack">حمله {number(group.labels.attack)}</span>
      <span className="normal">نرمال {number(group.labels.normal)}</span>
      <span>نامشخص {number(group.labels.unknown)}</span>
    </span>
  );
}
function Pages({
  offset,
  count,
  onChange,
}: {
  offset: number;
  count: number;
  onChange: (n: number) => void;
}) {
  return (
    <div className="hi-pages">
      <button
        className="days-button"
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - 10))}
      >
        قبلی
      </button>
      <span>
        صفحهٔ {number(Math.floor(offset / 10) + 1)} از{" "}
        {number(Math.max(1, Math.ceil(count / 10)))}
      </span>
      <button
        className="days-button"
        disabled={offset + 10 >= count}
        onClick={() => onChange(offset + 10)}
      >
        بعدی
      </button>
    </div>
  );
}
function Filter({
  value,
  onChange,
  name,
}: {
  value: string;
  onChange: (v: string) => void;
  name: string;
}) {
  return (
    <label>
      فیلتر برچسب
      <select
        aria-label={name}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="all">همه</option>
        <option value="attack">دارای دادهٔ حمله</option>
        <option value="normal">دارای دادهٔ نرمال</option>
        <option value="unknown">دارای دادهٔ نامشخص</option>
      </select>
    </label>
  );
}
function ErrorLine({ message, retry }: { message: string; retry: () => void }) {
  return (
    <p role="alert" className="hi-error">
      {message}
      <button className="days-button" onClick={retry}>
        تلاش دوباره
      </button>
    </p>
  );
}

export default function HierarchyExplorer({
  day,
  navigation,
  onNavigate,
}: {
  day: InventoryDay;
  navigation?: InspectionNavigation;
  onNavigate?: (v: InspectionNavigation) => void;
}) {
  const [local, setLocal] = useState<InspectionNavigation>({});
  const view = navigation ?? local;
  const navigate = (v: InspectionNavigation) => {
    const next = { chunkIndex: view.chunkIndex, ...v };
    return onNavigate ? onNavigate(next) : setLocal(next);
  };
  const chunkQuery =
    view.chunkIndex === undefined ? "" : `&chunk_index=${view.chunkIndex}`;
  const context = useApi<InspectionContext>(inspectionRoot(day.day));
  const explicit = useApi<InspectionReport>(
    view.reportId
      ? apiPath(`days/${day.day}/inspection/reports/${view.reportId}/`)
      : null,
  );
  const report = view.reportId ? explicit.data : context.data?.report;
  const prefix = report
    ? apiPath(`days/${day.day}/inspection/reports/${report.id}/`)
    : null;
  const explorer = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!prefix || !(view.metaId || view.componentId || view.observationId))
      return;
    const target = view.observationId
      ? "#hi-original"
      : view.componentId
        ? "#hi-observations"
        : "#hi-components";
    const heading = explorer.current?.querySelector<HTMLElement>(target);
    heading?.scrollIntoView({ block: "start" });
    heading?.focus({ preventScroll: true });
  }, [prefix, view.metaId, view.componentId, view.observationId]);

  const [metaLabel, setMetaLabel] = useState("all");
  const [componentLabel, setComponentLabel] = useState("all");
  const [observationLabel, setObservationLabel] = useState("all");
  const [representative, setRepresentative] = useState("all");
  const [metaOffset, setMetaOffset] = useState(0);
  const [componentOffset, setComponentOffset] = useState(0);
  const [observationOffset, setObservationOffset] = useState(0);
  const [ipInput, setIpInput] = useState("");
  const [ip, setIp] = useState("");
  const metas = useApi<Page<InspectionMeta>>(
    prefix
      ? `${prefix}metas/?limit=10&offset=${metaOffset}&label=${metaLabel}${chunkQuery}`
      : null,
  );
  const componentPath =
    prefix && view.metaId
      ? `${prefix}metas/${encodeURIComponent(view.metaId)}/components/`
      : null;
  const components = useApi<Page<InspectionComponent>>(
    componentPath
      ? `${componentPath}?limit=10&offset=${componentOffset}&label=${componentLabel}${chunkQuery}`
      : null,
  );
  const observationPath =
    componentPath && view.componentId
      ? `${componentPath}${encodeURIComponent(view.componentId)}/observations/`
      : null;
  const observations = useApi<Page<InspectionObservation>>(
    observationPath
      ? `${observationPath}?${new URLSearchParams({ limit: "10", offset: String(observationOffset), label: observationLabel, representative, ...(ip ? { ip } : {}) })}`
      : null,
  );
  const detail = useApi<InspectionFlow>(
    observationPath && view.observationId
      ? `${observationPath}${encodeURIComponent(view.observationId)}/`
      : null,
  );
  const [posting, setPosting] = useState(false);
  const [buildError, setBuildError] = useState("");
  const [jobState, setJobState] = useState<{
    scope: string;
    job?: InspectionJob;
    error?: string;
  }>({ scope: "" });
  const [pollAttempt, setPollAttempt] = useState(0);
  const scope = `${day.day}:${view.jobId}`;
  const job = jobState.scope === scope ? jobState.job : undefined;
  const accepted = useRef<{ identity: string; key: string } | null>(null);
  const inFlight = useRef<AbortController | null>(null);
  const finished = useRef<string | null>(null);
  useEffect(() => () => inFlight.current?.abort(), []);
  useEffect(() => {
    if (!view.jobId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await getJSON<InspectionJob>(
          `${inspectionRoot(day.day)}jobs/${view.jobId}/`,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        setJobState({ scope, job: result });
        if (result.status === "queued" || result.status === "running")
          timer = setTimeout(poll, 10000);
      } catch (e) {
        if (!controller.signal.aborted)
          setJobState((previous) => ({
            scope,
            job: previous.scope === scope ? previous.job : undefined,
            error: (e as Error).message,
          }));
      }
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [scope, day.day, view.jobId, pollAttempt]);
  useEffect(() => {
    if (job?.status === "succeeded" && finished.current !== job.id) {
      finished.current = job.id;
      context.retry();
      if (view.reportId !== job.report_id)
        navigate({ reportId: job.report_id, jobId: job.id });
      setMetaOffset(0);
      setComponentOffset(0);
      setObservationOffset(0);
    }
  }, [job?.id, job?.status]);
  const busy = posting || job?.status === "queued" || job?.status === "running";
  async function build(fresh = false) {
    if (
      inFlight.current ||
      !(context.data?.can_build ?? context.data?.available_hierarchy)
    )
      return;
    const snapshot = context.data?.inventory_snapshot_id ?? day.snapshot_id;
    const identity = `${day.day}:${snapshot}:${context.data?.active_hierarchy_run_id}:${context.data?.ready_chunk_indices?.join(",")}`;
    if (fresh || accepted.current?.identity !== identity)
      accepted.current = { identity, key: crypto.randomUUID() };
    const controller = new AbortController();
    inFlight.current = controller;
    setPosting(true);
    setBuildError("");
    try {
      const payload = await createInspection(
        day.day,
        snapshot,
        null,
        accepted.current.key,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setJobState({ scope: `${day.day}:${payload.job.id}`, job: payload.job });
      navigate({ ...view, jobId: payload.job.id });
    } catch (e) {
      if (!controller.signal.aborted) setBuildError((e as Error).message);
    } finally {
      if (!controller.signal.aborted) setPosting(false);
      inFlight.current = null;
    }
  }
  function selectMeta(id: string) {
    navigate({ reportId: report!.id, metaId: id, jobId: view.jobId });
    setComponentOffset(0);
    setObservationOffset(0);
    setComponentLabel("all");
    setObservationLabel("all");
    setIp("");
    setIpInput("");
    setRepresentative("all");
  }
  function selectComponent(id: string) {
    navigate({
      ...view,
      reportId: report!.id,
      componentId: id,
      observationId: undefined,
    });
    setObservationOffset(0);
    setObservationLabel("all");
    setIp("");
    setIpInput("");
    setRepresentative("all");
  }
  const stale =
    report &&
    (report.inventory_snapshot_id !==
      (context.data?.inventory_snapshot_id ?? day.snapshot_id) ||
      (report.source_kind === "available_components"
        ? (report.included_chunk_indices ?? []).join(",") !==
          (context.data?.ready_chunk_indices ?? []).join(",")
        : report.hierarchy_run_id !== context.data?.active_hierarchy_run_id));
  const fields = detail.data
    ? Object.keys(detail.data.raw_fields).filter(
        (k) =>
          [
            "src_ip",
            "dst_ip",
            "src_port",
            "dst_port",
            "protocol",
            "label",
            "label_binary",
          ].includes(k) ||
          [
            detail.data!.raw_fields[k],
            detail.data!.normalized_fields[k],
            detail.data!.candidate_fields[k],
          ].some((v) => v !== null && v !== undefined),
      )
    : [];
  return (
    <section
      ref={explorer}
      className="hi-explorer"
      aria-label="مرور سلسله‌مراتبی داده‌های روز"
    >
      <div className="hi-heading">
        <div>
          <h3>
            <Layers3 size={19} />
            گزارش سلسله‌مراتبی روز
          </h3>
          <p>
            فرامولفه ← مولفهٔ چانک ← مشاهده ← دادهٔ اصلی؛ بر اساس ارتباط
            ذخیره‌شده و برچسب داده.
          </p>
        </div>
        <div className="hi-actions">
          <button
            className="days-button"
            disabled={
              busy ||
              !(context.data?.can_build ?? context.data?.available_hierarchy)
            }
            onClick={() =>
              void build(
                !buildError &&
                  Boolean(
                    report ||
                    job?.status === "failed" ||
                    job?.status === "interrupted",
                  ),
              )
            }
          >
            <Database size={15} />
            {busy
              ? "در حال ساخت گزارش جزئیات…"
              : report
                ? "به‌روزرسانی گزارش جزئیات"
                : "ساخت گزارش جزئیات"}
          </button>
          <button
            className="days-button"
            onClick={() => {
              context.retry();
              explicit.retry();
            }}
          >
            بازخوانی گزارش
          </button>
        </div>
      </div>
      {(context.loading || explicit.loading) && (
        <p className="hi-note" role="status">
          در حال دریافت گزارش ذخیره‌شده…
        </p>
      )}
      {context.error && (
        <ErrorLine message={context.error.message} retry={context.retry} />
      )}
      {explicit.error && (
        <ErrorLine message={explicit.error.message} retry={explicit.retry} />
      )}
      {(buildError || (jobState.scope === scope && jobState.error)) && (
        <ErrorLine
          message={buildError || jobState.error!}
          retry={() => {
            if (buildError) void build();
            else setPollAttempt((v) => v + 1);
          }}
        />
      )}
      {job && (
        <p className="hi-note" role="status">
          {job.status === "queued"
            ? `گزارش در صف است؛ جایگاه ${number(job.queue_position)}.`
            : job.status === "running"
              ? "گزارش جزئیات در حال استخراج و اعتبارسنجی ارتباط داده‌هاست."
              : job.status === "succeeded"
                ? "گزارش جزئیات ذخیره شد."
                : "ساخت گزارش انجام نشد؛ سازگاری سلسله‌مراتب و داده‌های مبدأ را بررسی و گزارش تازه درخواست کنید."}
          {(job.status === "queued" || job.status === "running") &&
          !job.worker.online
            ? " worker گزارش فعال نیست؛ run_api_worker را بررسی کنید."
            : ""}
        </p>
      )}
      {!context.loading &&
        context.data &&
        !(context.data.can_build ?? context.data.available_hierarchy) && (
          <p className="hi-warning">
            هنوز چانک آمادهٔ دارای گراف و مولفه برای این روز موجود نیست.
            آماده‌شدن حتی یک چانک برای ساخت گزارش کافی است؛ نیازی به تکمیل همهٔ
            روز نیست. گزارش آرشیوی همچنان قابل مرور است.
          </p>
        )}
      {!context.loading &&
        context.data?.can_build &&
        !context.data.available_hierarchy && (
          <p className="hi-note" role="status">
            گزارش از {number(context.data.ready_chunk_count)} چانک آمادهٔ موجود
            ساخته می‌شود؛ نبود فرامولفهٔ روزانهٔ ذخیره‌شده مانع ساخت گزارش جزئی
            نیست.
          </p>
        )}
      {!report && !context.loading && !explicit.loading && !explicit.error && (
        <p className="hi-note">
          گزارش هنوز ذخیره نشده است. با ساخت گزارش جزئیات، چانک‌های آماده خوانده
          می‌شوند؛ چانک‌های ناتمام کنار گذاشته شده و پوشش گزارش مشخص می‌شود.
          برچسب حمله از دادهٔ ذخیره‌شده خوانده می‌شود.
        </p>
      )}
      {view.chunkIndex !== undefined && (
        <div className="hi-chunk-scope" role="note">
          <div>
            <Layers3 size={16} />
            <strong>مرور چانک {number(view.chunkIndex)}</strong>
            <span>
              فرامولفه‌های مرتبط و مولفه‌های همین چانک نمایش داده می‌شوند؛ آمار
              خلاصه و آمار هر فرامولفه مربوط به کل گزارش ذخیره‌شده است.
            </span>
          </div>
          <button
            className="days-text-button"
            onClick={() => {
              setMetaOffset(0);
              setComponentOffset(0);
              setObservationOffset(0);
              navigate({
                reportId: report?.id,
                jobId: view.jobId,
                chunkIndex: undefined,
              });
            }}
          >
            نمایش گزارش کل روز
          </button>
        </div>
      )}
      {report && (
        <>
          <div className="hi-summary">
            {[
              ["فرامولفه", report.meta_count],
              ["مولفهٔ چانک", report.component_count],
              ["مشاهدهٔ کاندید", report.observation_count],
              ["فرامولفهٔ دارای حمله", report.attack_meta_count],
              ["فرامولفهٔ دارای نرمال", report.normal_meta_count],
              ["فرامولفهٔ دارای نامشخص", report.unknown_meta_count],
            ].map(([label, count]) => (
              <div key={String(label)}>
                <span>{label}</span>
                <strong>{number(Number(count))}</strong>
              </div>
            ))}
          </div>
          {view.chunkIndex !== undefined &&
            report.included_chunk_indices &&
            !report.included_chunk_indices.includes(view.chunkIndex) && (
              <p className="hi-warning" role="status">
                چانک {number(view.chunkIndex)} در این نسخهٔ گزارش وجود ندارد.
                می‌توانید گزارش را از خروجی‌های آمادهٔ فعلی دوباره بسازید یا
                جزئیات چانک را باز کنید.
              </p>
            )}
          {report.included_chunk_indices && (
            <p className="hi-note">
              چانک‌های گزارش:{" "}
              <bdi>{report.included_chunk_indices.map(number).join("، ")}</bdi>{" "}
              · {number(report.included_chunk_indices.length)} از{" "}
              {number(report.expected_chunk_count)} چانک مورد انتظار
              {report.missing_chunk_indices?.length
                ? ` · چانک‌های خارج از این گزارش: ${report.missing_chunk_indices.map(number).join("، ")}`
                : ""}
              .{" "}
              {report.source_kind === "available_components"
                ? "فرامولفه‌ها برای همین گزارش از چانک‌های آماده محاسبه شده‌اند."
                : ""}
            </p>
          )}
          <p className="hi-note">
            <Counts group={report} /> · نمایندهٔ لایهٔ اول:{" "}
            {number(report.layer1_representatives)} · نمایندهٔ روزانه:{" "}
            {number(report.daily_representatives)} · دادهٔ اصلی ناموجود:{" "}
            {number(report.missing_raw_records)}
          </p>
          <p className="hi-note">
            این برچسب‌ها از دادهٔ ذخیره‌شده‌اند و نتیجهٔ پیش‌بینی حمله نیستند.
            گروه‌های مختلط می‌توانند در فیلتر حمله و نرمال هر دو ظاهر شوند.
            مشاهدات این گزارش کاندیدهای حاضر در سلسله‌مراتب‌اند، نه تمام
            رکوردهای خام روز.
          </p>
          <details className="hi-provenance">
            <summary>نسخه و منشأ گزارش</summary>
            <dl>
              <dt>شناسهٔ گزارش</dt>
              <dd>
                <bdi>{report.id}</bdi>
              </dd>
              <dt>نسخهٔ سلسله‌مراتب</dt>
              <dd>
                <bdi>
                  {report.hierarchy_run_id ??
                    "گزارش از چانک‌های آماده؛ بدون تغییر نسخهٔ فعال"}
                </bdi>
              </dd>
              <dt>نسخهٔ نمایندهٔ روزانه</dt>
              <dd>
                <bdi>{report.daily_representative_run_id ?? "—"}</bdi>
              </dd>
              <dt>زمان مشاهده / تهران</dt>
              <dd>
                {new Intl.DateTimeFormat("fa-IR", {
                  timeZone: "Asia/Tehran",
                  dateStyle: "short",
                  timeStyle: "short",
                }).format(new Date(report.generated_at))}
              </dd>
              <dt>پوشش روز</dt>
              <dd>
                {report.coverage_status === "complete"
                  ? "کامل"
                  : report.coverage_status === "partial"
                    ? "جزئی"
                    : "تأییدنشده"}
              </dd>
            </dl>
          </details>
          {stale && (
            <p className="hi-warning" role="status">
              نسخهٔ فعال روز یا اطلاعات کالکشن روزها با این گزارش متفاوت است.
              این مرور روی نسخهٔ ذخیره‌شدهٔ گزارش ثابت می‌ماند؛ برای مشاهدهٔ
              جدید، گزارش تازه بسازید.
            </p>
          )}
          <nav className="hi-breadcrumb" aria-label="مسیر داده">
            <button
              onClick={() =>
                navigate({ reportId: report.id, jobId: view.jobId })
              }
            >
              فرامولفه‌ها
            </button>
            {view.metaId && (
              <>
                <ChevronLeft size={14} />
                <button
                  onClick={() =>
                    navigate({
                      reportId: report.id,
                      metaId: view.metaId,
                      jobId: view.jobId,
                    })
                  }
                >
                  فرامولفه <bdi>{short(view.metaId)}</bdi>
                </button>
              </>
            )}
            {view.componentId && (
              <>
                <ChevronLeft size={14} />
                <button
                  onClick={() =>
                    navigate({ ...view, observationId: undefined })
                  }
                >
                  مولفه <bdi>{short(view.componentId)}</bdi>
                </button>
              </>
            )}
            {view.observationId && (
              <>
                <ChevronLeft size={14} />
                <span>
                  دادهٔ اصلی <bdi>{short(view.observationId)}</bdi>
                </span>
              </>
            )}
          </nav>
          <section className="hi-level" aria-labelledby="hi-metas">
            <div className="hi-level-heading">
              <h4 id="hi-metas" tabIndex={-1}>
                ۱. فرامولفه‌های روزانه
              </h4>
              <Filter
                name="فیلتر برچسب فرامولفه"
                value={metaLabel}
                onChange={(v) => {
                  setMetaLabel(v);
                  setMetaOffset(0);
                  navigate({ reportId: report.id, jobId: view.jobId });
                }}
              />
            </div>
            {metas.error && (
              <ErrorLine message={metas.error.message} retry={metas.retry} />
            )}
            {metas.loading && <p role="status">در حال دریافت فرامولفه‌ها…</p>}
            <div
              className="hi-table-scroll"
              role="region"
              aria-labelledby="hi-metas"
              tabIndex={0}
            >
              <table>
                <thead>
                  <tr>
                    <th>فرامولفه</th>
                    <th>مولفه / مشاهده</th>
                    <th>برچسب‌ها</th>
                    <th>ترکیب</th>
                    <th>نمایندهٔ روزانه</th>
                    <th>مرور</th>
                  </tr>
                </thead>
                <tbody>
                  {metas.data?.results.map((meta) => (
                    <tr
                      key={meta.meta_id}
                      className={view.metaId === meta.meta_id ? "selected" : ""}
                    >
                      <th scope="row">
                        M{number(meta.meta_index)}
                        <small>
                          <bdi>{meta.meta_id}</bdi>
                        </small>
                      </th>
                      <td>
                        {number(meta.component_count)} /{" "}
                        {number(meta.observation_count)}
                      </td>
                      <td>
                        <Counts group={meta} />
                      </td>
                      <td>{compositionNames[meta.composition]}</td>
                      <td>{number(meta.daily_representatives)}</td>
                      <td>
                        <button
                          className="days-button"
                          onClick={() => selectMeta(meta.meta_id)}
                          aria-label={`مشاهده مولفه‌های فرامولفه ${meta.meta_index}`}
                        >
                          مولفه‌ها
                          <ChevronLeft size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {metas.data?.count === 0 && (
              <p className="hi-note">فرامولفه‌ای با این فیلتر وجود ندارد.</p>
            )}
            {metas.data && (
              <Pages
                offset={metaOffset}
                count={metas.data.count}
                onChange={setMetaOffset}
              />
            )}
          </section>
          {view.metaId && (
            <section className="hi-level" aria-labelledby="hi-components">
              <div className="hi-level-heading">
                <h4 id="hi-components" tabIndex={-1}>
                  ۲. مولفه‌های فرامولفهٔ انتخاب‌شده
                </h4>
                <Filter
                  name="فیلتر برچسب مولفه"
                  value={componentLabel}
                  onChange={(v) => {
                    setComponentLabel(v);
                    setComponentOffset(0);
                    navigate({
                      ...view,
                      componentId: undefined,
                      observationId: undefined,
                    });
                  }}
                />
              </div>
              {components.error && (
                <ErrorLine
                  message={components.error.message}
                  retry={components.retry}
                />
              )}
              {components.loading && (
                <p role="status">در حال دریافت مولفه‌ها…</p>
              )}
              <div
                className="hi-table-scroll"
                role="region"
                aria-labelledby="hi-components"
                tabIndex={0}
              >
                <table>
                  <thead>
                    <tr>
                      <th>مولفه</th>
                      <th>چانک</th>
                      <th>مشاهدات</th>
                      <th>برچسب‌ها</th>
                      <th>نمایندهٔ لایهٔ اول / روزانه</th>
                      <th>مرور</th>
                    </tr>
                  </thead>
                  <tbody>
                    {components.data?.results.map((component) => (
                      <tr
                        key={component.component_id}
                        className={
                          view.componentId === component.component_id
                            ? "selected"
                            : ""
                        }
                      >
                        <th scope="row">
                          C{number(component.component_index)}
                          <small>
                            <bdi>{component.component_id}</bdi>
                          </small>
                        </th>
                        <td>{number(component.chunk_index)}</td>
                        <td>{number(component.observation_count)}</td>
                        <td>
                          <Counts group={component} />
                        </td>
                        <td>
                          {number(component.layer1_representatives)} /{" "}
                          {number(component.daily_representatives)}
                        </td>
                        <td>
                          <button
                            className="days-button"
                            onClick={() =>
                              selectComponent(component.component_id)
                            }
                            aria-label={`مشاهده داده‌های مولفه ${component.component_id}`}
                          >
                            مشاهدات
                            <ChevronLeft size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {components.data?.count === 0 && (
                <p className="hi-note">مولفه‌ای با این فیلتر وجود ندارد.</p>
              )}
              {components.data && (
                <Pages
                  offset={componentOffset}
                  count={components.data.count}
                  onChange={setComponentOffset}
                />
              )}
            </section>
          )}
          {view.componentId && (
            <section className="hi-level" aria-labelledby="hi-observations">
              <div className="hi-level-heading">
                <h4 id="hi-observations" tabIndex={-1}>
                  ۳. مشاهدات مولفه و ارتباط با دادهٔ اصلی
                </h4>
                <Filter
                  name="فیلتر برچسب مشاهده"
                  value={observationLabel}
                  onChange={(v) => {
                    setObservationLabel(v);
                    setObservationOffset(0);
                    navigate({ ...view, observationId: undefined });
                  }}
                />
              </div>
              <div className="hi-observation-filters">
                <label>
                  نماینده
                  <select
                    aria-label="فیلتر نماینده"
                    value={representative}
                    onChange={(e) => {
                      setRepresentative(e.target.value);
                      setObservationOffset(0);
                      navigate({ ...view, observationId: undefined });
                    }}
                  >
                    <option value="all">همهٔ مشاهدات</option>
                    <option value="layer1">نمایندهٔ لایهٔ اول</option>
                    <option value="daily">نمایندهٔ روزانه</option>
                  </select>
                </label>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    setIp(ipInput.trim());
                    setObservationOffset(0);
                    navigate({ ...view, observationId: undefined });
                  }}
                >
                  <label>
                    IP اصلی مبدأ یا مقصد
                    <input
                      aria-label="جستجوی IP اصلی"
                      value={ipInput}
                      onChange={(e) => setIpInput(e.target.value)}
                      placeholder="192.0.2.1"
                      dir="ltr"
                    />
                  </label>
                  <button className="days-button" type="submit">
                    <Search size={14} />
                    جستجو
                  </button>
                </form>
              </div>
              {representative === "daily" &&
                report.daily_representative_run_id === null && (
                  <p className="hi-note">
                    نسخهٔ نمایندهٔ روزانه برای این گزارش موجود نیست؛ نبود نتیجهٔ
                    این فیلتر به معنای صفر بودن یک اندازه‌گیری کامل نیست.
                  </p>
                )}
              {observations.error && (
                <ErrorLine
                  message={observations.error.message}
                  retry={observations.retry}
                />
              )}
              {observations.loading && (
                <p role="status">در حال دریافت مشاهدات…</p>
              )}
              <div
                className="hi-table-scroll"
                role="region"
                aria-labelledby="hi-observations"
                tabIndex={0}
              >
                <table>
                  <thead>
                    <tr>
                      <th>شناسهٔ مشاهده / اصلی</th>
                      <th>برچسب</th>
                      <th>مبدأ اصلی</th>
                      <th>مقصد اصلی</th>
                      <th>نمایندهٔ لایهٔ اول / روزانه</th>
                      <th>جزئیات</th>
                    </tr>
                  </thead>
                  <tbody>
                    {observations.data?.results.map((observation) => (
                      <tr
                        key={observation.observation_id}
                        className={
                          view.observationId === observation.observation_id
                            ? "selected"
                            : ""
                        }
                      >
                        <th scope="row">
                          <bdi>{observation.observation_id}</bdi>
                          <small>
                            <bdi>{observation.original_id}</bdi>
                          </small>
                        </th>
                        <td>
                          <span className={`hi-label ${observation.label}`}>
                            {labelNames[observation.label]}
                          </span>
                          {!observation.raw_available && (
                            <small>رکورد اصلی موجود نیست</small>
                          )}
                        </td>
                        <td>
                          <bdi>
                            {value(observation.raw_summary.src_ip)} :{" "}
                            {value(observation.raw_summary.src_port)}
                          </bdi>
                        </td>
                        <td>
                          <bdi>
                            {value(observation.raw_summary.dst_ip)} :{" "}
                            {value(observation.raw_summary.dst_port)}
                          </bdi>
                        </td>
                        <td>
                          {observation.layer1_representative ? "بله" : "خیر"} /{" "}
                          {observation.daily_representative === null
                            ? "—"
                            : observation.daily_representative
                              ? "بله"
                              : "خیر"}
                        </td>
                        <td>
                          <button
                            className="days-button"
                            onClick={() =>
                              navigate({
                                ...view,
                                observationId: observation.observation_id,
                              })
                            }
                            aria-label={`جزئیات داده اصلی ${observation.observation_id}`}
                          >
                            دادهٔ اصلی
                            <ChevronLeft size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {observations.data?.count === 0 && (
                <p className="hi-note">مشاهده‌ای با این فیلتر وجود ندارد.</p>
              )}
              {observations.data && (
                <Pages
                  offset={observationOffset}
                  count={observations.data.count}
                  onChange={setObservationOffset}
                />
              )}
            </section>
          )}
          {view.observationId && (
            <section className="hi-level hi-flow" aria-labelledby="hi-original">
              <h4 id="hi-original" tabIndex={-1}>
                <Database size={17} />
                ۴. جزئیات دادهٔ اصلی و مقایسه با ویژگی‌های پردازش‌شده
              </h4>
              {detail.error && (
                <ErrorLine
                  message={detail.error.message}
                  retry={detail.retry}
                />
              )}
              {detail.loading && <p role="status">در حال دریافت جزئیات…</p>}
              {detail.data && (
                <>
                  <dl className="hi-record-meta">
                    <dt>شناسهٔ اصلی</dt>
                    <dd>
                      <bdi>{detail.data.original_id}</bdi>
                    </dd>
                    <dt>شناسهٔ کاندید</dt>
                    <dd>
                      <bdi>{detail.data.observation_id}</bdi>
                    </dd>
                    <dt>برچسب / منشأ</dt>
                    <dd>
                      <span className={`hi-label ${detail.data.label}`}>
                        {labelNames[detail.data.label]}
                      </span>{" "}
                      ·{" "}
                      {detail.data.label_origin === "raw"
                        ? "دادهٔ اصلی"
                        : detail.data.label_origin === "candidate"
                          ? "برچسب کاندید ذخیره‌شده"
                          : detail.data.label_origin === "conflict"
                            ? "تعارض برچسب‌ها"
                            : "نامشخص"}
                    </dd>
                    <dt>نام فایل / شمارهٔ سطر</dt>
                    <dd>
                      <bdi>{detail.data.source_file_basename ?? "—"}</bdi> /{" "}
                      {number(detail.data.row_index)}
                    </dd>
                  </dl>
                  {!detail.data.raw_available && (
                    <p className="hi-warning">
                      <AlertTriangle size={15} />
                      رکورد اصلی هنگام ساخت این گزارش موجود نبود؛ مقادیر اصلی از
                      دادهٔ نرمال‌شده بازسازی نشده‌اند.
                    </p>
                  )}
                  {detail.data.label_origin === "conflict" && (
                    <p className="hi-warning">
                      برچسب اصلی و پردازش‌شده سازگار نیستند؛ طبقه‌بندی این
                      مشاهده نامشخص نگه داشته شده است.
                    </p>
                  )}
                  <p className="hi-note">
                    مقادیر، تصویر ذخیره‌شده در زمان ساخت گزارش‌اند. ستون اصلی
                    مقدار خام است؛ اعداد نرمال‌شدهٔ IP و پورت، IP و پورت اصلی
                    نیستند. «—» یعنی مقدار در آن لایه موجود نیست.
                  </p>
                  <div
                    className="hi-table-scroll"
                    role="region"
                    aria-labelledby="hi-original"
                    tabIndex={0}
                  >
                    <table className="hi-fields">
                      <thead>
                        <tr>
                          <th>فیلد</th>
                          <th>مقدار اصلی</th>
                          <th>مقدار نرمال‌شده</th>
                          <th>مقدار کاندید ذخیره‌شده</th>
                        </tr>
                      </thead>
                      <tbody>
                        {fields.map((field) => (
                          <tr key={field}>
                            <th scope="row">
                              {fieldNames[field] ?? field}
                              <small>
                                <bdi>{field}</bdi>
                              </small>
                            </th>
                            <td>
                              <bdi>{value(detail.data!.raw_fields[field])}</bdi>
                            </td>
                            <td>
                              <bdi>
                                {value(detail.data!.normalized_fields[field])}
                              </bdi>
                            </td>
                            <td>
                              <bdi>
                                {value(detail.data!.candidate_fields[field])}
                              </bdi>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {Object.values(detail.data.omitted_fields).some(
                    (v) => v.length > 0,
                  ) && (
                    <p className="hi-note">
                      مقادیر غیرمتناهی، مرکب یا بزرگ‌تر از حد نمایش کنار گذاشته
                      شده‌اند:{" "}
                      {Object.entries(detail.data.omitted_fields)
                        .filter(([, v]) => v.length)
                        .map(([k, v]) => `${k}: ${v.join(", ")}`)
                        .join(" · ")}
                    </p>
                  )}
                </>
              )}
            </section>
          )}
        </>
      )}
    </section>
  );
}
