import { useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  BrainCircuit,
  Download,
  SlidersHorizontal,
  FlaskConical,
  Info,
  CalendarDays,
  ArrowUpLeft,
  Layers3,
  Fingerprint,
  Check,
  FileClock,
} from "lucide-react";
import { dateLabel, number } from "../data/days";
import {
  availableGraphChunks,
  downloadModelJSON,
  editorFromModel,
  familyLabels,
  lossHistory,
  mockModelRuns,
  modelStatusLabels,
  previewRequest,
  type ModelConfig,
  type ModelRun,
  type ModelVariant,
} from "../data/models";
import { dayDetailsPath } from "../lib/dayNavigation";
import { ModelOverview } from "../components/models/ModelOverview";
import { HyperparameterEditor } from "../components/models/HyperparameterEditor";
import { BehaviorPanel } from "../components/models/BehaviorPanel";
import { ModelRegistry } from "../components/models/ModelRegistry";
import "./models.css";

const tabs = [
  { id: "overview", label: "نمای مدل", icon: BrainCircuit },
  { id: "parameters", label: "هایپرپارامترها", icon: SlidersHorizontal },
  { id: "behavior", label: "رفتار و مرجع نرمال", icon: Fingerprint },
] as const;
type ModelTab = (typeof tabs)[number]["id"];

export function ModelsPage() {
  const [params, setParams] = useSearchParams();
  const [runs, setRuns] = useState<ModelRun[]>(mockModelRuns);
  const runsRef = useRef(runs);
  const requested = params.get("model");
  const selected =
    runs.find((run) => run.id === requested) ??
    runs.find((run) => run.id === mockModelRuns[0].id)!;
  const [tab, setTab] = useState<ModelTab>("overview");
  const [variant, setVariant] = useState<ModelVariant>("spectral");
  const [editor, setEditor] = useState(() => editorFromModel(selected));
  const [editorKey, setEditorKey] = useState(0);
  const [notice, setNotice] = useState("");
  const [registryKey, setRegistryKey] = useState(0);
  const created = new Intl.DateTimeFormat("fa-IR", {
    timeZone: "Asia/Tehran",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(selected.createdAt));
  function selectModel(id: string) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("model", id);
      return next;
    });
    document
      .getElementById("selected-model")
      ?.scrollIntoView({ block: "start", behavior: "auto" });
  }
  function loadSelected() {
    setEditor(editorFromModel(selected));
  }
  function saveDraft(config: ModelConfig) {
    const existing = runsRef.current.find(
      (run) =>
        run.status === "draft" &&
        run.baseId === editor.baseId &&
        JSON.stringify(run.config) === JSON.stringify(config),
    );
    if (existing) {
      selectModel(existing.id);
      setTab("overview");
      setRegistryKey((value) => value + 1);
      setNotice(
        `همین تنظیمات قبلاً در ${existing.version} ثبت شده است؛ نسخهٔ تکراری ساخته نشد.`,
      );
      return;
    }
    const next: ModelRun = {
      id: `mock-draft-${crypto.randomUUID().slice(0, 8)}`,
      version: `v0.${runsRef.current.length + 1}`,
      title: "پیش‌نویس آموزش جدید",
      status: "draft",
      config: structuredClone(config),
      baseId: editor.baseId,
      createdAt: new Date().toISOString(),
      metrics: null,
      reference: null,
      activeFeatures: null,
      graphChunks: availableGraphChunks(config.day),
    };
    runsRef.current = [next, ...runsRef.current];
    setRuns(runsRef.current);
    selectModel(next.id);
    setTab("overview");
    setRegistryKey((value) => value + 1);
    setNotice(
      `پیش‌نویس ${next.version} ثبت شد. هیچ آموزش، امتیاز یا وزن جدیدی تولید نشده است.`,
    );
  }
  function downloadCard() {
    downloadModelJSON(`mock-model-card-${selected.id}.json`, {
      mock: true,
      weights_loaded: false,
      exported_at: new Date().toISOString(),
      model: selected,
      displayed_variant: variant,
      history: lossHistory(selected, variant),
      fixed_parameters: {
        optimizer: "Adam",
        learning_rate: 0.001,
        weight_decay: 0.0001,
        gradient_clip_norm: 5,
        feature_mask_rate: 0.2,
      },
      request_preview: previewRequest(selected.config),
    });
    setNotice(
      `کارت مدل ${selected.version} به‌صورت JSON ماک دانلود شد؛ فایل وزن واقعی نیست.`,
    );
  }
  return (
    <main id="main-content" className="main-content models-page" tabIndex={-1}>
      <div className="page-heading mdl-page-heading">
        <div>
          <p className="eyebrow">تحلیل و پردازش / مدیریت چرخهٔ مدل</p>
          <h1>مدل و رفتار</h1>
          <p className="page-description">
            نسخه‌های مدل، تنظیمات آموزش و ارزیابی رفتار؛ با منشأ مشخص برای هر
            نتیجه.
          </p>
        </div>
        <span className="mdl-mock-badge">
          <FlaskConical size={15} />
          نسخهٔ ماک
        </span>
      </div>
      <div className="mdl-page-notice">
        <Info size={15} />
        <span>
          مدل‌ها، سنجه‌ها و مرجع‌ها نمایشی‌اند؛ checkpoint واقعی بارگذاری نشده و
          هیچ آموزش یا درخواست API اجرا نمی‌شود.
        </span>
      </div>
      {requested && !runs.some((run) => run.id === requested) && (
        <p className="mdl-unknown-model" role="status">
          نسخهٔ درخواستی در حافظهٔ این صفحه نیست؛ مدل نمونهٔ پیش‌فرض نمایش داده
          می‌شود. پیش‌نویس‌های محلی با بازخوانی صفحه پاک می‌شوند.
        </p>
      )}
      <section
        className="mdl-card mdl-selected-model"
        id="selected-model"
        aria-labelledby="selected-model-title"
      >
        <div className="mdl-selected-main">
          <span className="mdl-model-icon">
            <BrainCircuit size={28} strokeWidth={1.5} />
          </span>
          <div>
            <div className="mdl-selected-kicker">
              مدل منتخب برای مشاهده
              <span className={`mdl-state ${selected.status}`}>
                {modelStatusLabels[selected.status]}
              </span>
            </div>
            <h2 id="selected-model-title">
              {selected.title}
              <bdi>{selected.version}</bdi>
            </h2>
            <p>
              {familyLabels[selected.config.family]}
              <span>·</span>Layer 1<span>·</span>سه گونهٔ مشترک
            </p>
          </div>
          <div className="mdl-selected-actions">
            <button
              className="mdl-primary-button"
              onClick={() => {
                loadSelected();
                setEditorKey((value) => value + 1);
                setTab("parameters");
              }}
            >
              <SlidersHorizontal size={15} />
              پیکربندی از این نسخه
            </button>
            <button className="mdl-secondary-button" onClick={downloadCard}>
              <Download size={14} />
              کارت مدل JSON
            </button>
          </div>
        </div>
        <div className="mdl-selected-meta">
          <span>
            <Fingerprint size={14} />
            <bdi>{selected.id}</bdi>
          </span>
          <span>
            <CalendarDays size={14} />
            روز داده: {dateLabel(selected.config.day)}
          </span>
          <span>
            <Layers3 size={14} />
            {number(selected.graphChunks.length)} چانک منبع
          </span>
          <Link to={dayDetailsPath(selected.config.day)}>
            روز داده
            <ArrowUpLeft size={13} />
          </Link>
        </div>
        <div className="mdl-selected-time">
          ثبت نمونه: {created}
          {selected.baseId && (
            <span>
              منبع تنظیمات: <bdi>{selected.baseId}</bdi>
            </span>
          )}
        </div>
      </section>
      {notice && (
        <div className="mdl-action-notice" role="status">
          <Check size={15} />
          {notice}
        </div>
      )}
      {selected.status === "draft" && (
        <div className="mdl-draft-banner">
          <FileClock size={18} />
          <p>
            این نسخه فقط پیش‌نویس پارامترهاست؛ سنجه‌ها، منحنی و فایل وزن تا
            اجرای واقعی آموزش در دسترس نیستند.
          </p>
        </div>
      )}
      <div
        className="mdl-tabs"
        role="tablist"
        aria-label="بخش‌های مدل و رفتار"
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
            return;
          event.preventDefault();
          const focusedId = (event.target as HTMLElement).closest(
            '[role="tab"]',
          )?.id;
          const focusedIndex = tabs.findIndex(
            (item) => `model-tab-${item.id}` === focusedId,
          );
          const index =
            focusedIndex >= 0
              ? focusedIndex
              : tabs.findIndex((item) => item.id === tab);
          const target =
            event.key === "Home"
              ? 0
              : event.key === "End"
                ? tabs.length - 1
                : (index + (event.key === "ArrowLeft" ? 1 : -1) + tabs.length) %
                  tabs.length;
          setTab(tabs[target].id);
          document.getElementById(`model-tab-${tabs[target].id}`)?.focus();
        }}
      >
        {tabs.map((item) => (
          <button
            key={item.id}
            role="tab"
            id={`model-tab-${item.id}`}
            aria-selected={tab === item.id}
            aria-controls="model-tab-panel"
            tabIndex={tab === item.id ? 0 : -1}
            onClick={() => setTab(item.id)}
          >
            <item.icon size={16} />
            {item.label}
          </button>
        ))}
        <span>شناسه و تنظیمات نسخه‌ها مستقل می‌مانند</span>
      </div>
      <div
        role="tabpanel"
        id="model-tab-panel"
        className="mdl-tab-panel"
        aria-labelledby={`model-tab-${tab}`}
        tabIndex={0}
      >
        {tab === "overview" ? (
          <ModelOverview
            model={selected}
            variant={variant}
            onVariant={setVariant}
          />
        ) : tab === "parameters" ? (
          <HyperparameterEditor
            key={editorKey}
            editor={editor}
            setEditor={setEditor}
            onLoadSelected={loadSelected}
            onSave={saveDraft}
          />
        ) : (
          <BehaviorPanel model={selected} />
        )}
      </div>
      <ModelRegistry
        key={registryKey}
        runs={runs}
        selectedId={selected.id}
        onSelect={selectModel}
      />
      <div className="mdl-bottom-note">
        <FlaskConical size={14} />
        <span>
          مدیریت مدل به‌صورت نمایشی · بدون تغییر مدل ثبت‌شده، استقرار خودکار یا
          برچسب حمله
        </span>
      </div>
    </main>
  );
}
