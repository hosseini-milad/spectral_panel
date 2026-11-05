import { useRef } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  Layers3,
  GitBranch,
  FileBox,
  ArrowLeft,
  ArrowUpLeft,
  Info,
  LockKeyhole,
} from "lucide-react";
import { dateLabel, number } from "../../data/days";
import {
  lossHistory,
  modelSplits,
  scoreNumber,
  variantLabels,
  type ModelRun,
  type ModelVariant,
} from "../../data/models";
import { useSvgWidth } from "../../lib/useSvgWidth";
import { dayDetailsPath } from "../../lib/dayNavigation";

function LearningCurve({
  model,
  variant,
}: {
  model: ModelRun;
  variant: ModelVariant;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const width = useSvgWidth(svg, 620);
  const history = lossHistory(model, variant);
  const metric = model.metrics?.[variant];
  const left = 47,
    right = width - 18,
    top = 20,
    bottom = 208;
  const maximum =
    Math.ceil(
      Math.max(...history.flatMap((row) => [row.train, row.validation]), 0.1) *
        10,
    ) / 10;
  const x = (epoch: number) =>
    left +
    ((epoch - 1) / Math.max(1, model.config.epochs - 1)) * (right - left);
  const y = (loss: number) => bottom - (loss / maximum) * (bottom - top);
  return (
    <section
      className="mdl-card mdl-learning-curve"
      aria-labelledby="model-curve-title"
    >
      <div className="mdl-section-heading">
        <div>
          <Activity size={17} />
          <div>
            <h2 id="model-curve-title">روند آموزش و اعتبارسنجی</h2>
            <p>Loss هدف کل؛ پایین‌تر بهتر است · منحنی کاملاً ماک</p>
          </div>
        </div>
        <span>بهترین دوره: {metric ? number(metric.selectedEpoch) : "—"}</span>
      </div>
      {metric ? (
        <>
          <div className="mdl-chart-legend">
            <span>
              <i />
              آموزش
            </span>
            <span>
              <i className="validation" />
              اعتبارسنجی
            </span>
            <small>{variantLabels[variant]}</small>
          </div>
          <svg
            ref={svg}
            className="mdl-loss-svg"
            viewBox={`0 0 ${width} 245`}
            role="img"
            aria-label={`منحنی ماک آموزش ${variantLabels[variant]}؛ بهترین دوره ${metric.selectedEpoch}`}
            direction="ltr"
          >
            <title>منحنی نمایشی Loss؛ نتیجهٔ آموزش واقعی نیست</title>
            {Array.from({ length: 5 }, (_, index) => {
              const value = (maximum * index) / 4;
              return (
                <g key={index}>
                  <line
                    x1={left}
                    x2={right}
                    y1={y(value)}
                    y2={y(value)}
                    stroke="var(--chart-grid)"
                    strokeDasharray="4 5"
                  />
                  <text
                    x={left - 10}
                    y={y(value) + 4}
                    textAnchor="end"
                    className="mdl-chart-axis"
                  >
                    {scoreNumber(value, 1)}
                  </text>
                </g>
              );
            })}
            {[
              1,
              Math.round(model.config.epochs / 3),
              Math.round((model.config.epochs * 2) / 3),
              model.config.epochs,
            ].map((epoch) => (
              <text
                key={epoch}
                x={x(epoch)}
                y="232"
                textAnchor="middle"
                className="mdl-chart-axis"
              >
                {number(epoch)}
              </text>
            ))}
            <polyline
              points={history
                .map((row) => `${x(row.epoch)},${y(row.train)}`)
                .join(" ")}
              fill="none"
              stroke="var(--chart-green)"
              strokeWidth="2"
            />
            <polyline
              points={history
                .map((row) => `${x(row.epoch)},${y(row.validation)}`)
                .join(" ")}
              fill="none"
              stroke="var(--chart-blue)"
              strokeWidth="2"
            />
            <line
              x1={x(metric.selectedEpoch)}
              x2={x(metric.selectedEpoch)}
              y1={top}
              y2={bottom}
              stroke="var(--accent-border)"
              strokeDasharray="4 4"
            />
            <circle
              cx={x(metric.selectedEpoch)}
              cy={y(metric.validationLoss)}
              r="5"
              fill="var(--chart-blue)"
              stroke="var(--surface)"
              strokeWidth="2"
            >
              <title>{`دوره ${number(metric.selectedEpoch)}: ${scoreNumber(metric.validationLoss)}`}</title>
            </circle>
          </svg>
          <p className="mdl-curve-note">
            وزن‌ها با بهترین اعتبارسنجی انتخاب می‌شوند، نه با آزمون. محور افقی
            دورهٔ آموزش و محور عمودی Loss است.
          </p>
        </>
      ) : (
        <div className="mdl-panel-empty">
          <Activity size={28} />
          <strong>هنوز آموزشی اجرا نشده است</strong>
          <p>با ثبت پیش‌نویس، منحنی یا سنجهٔ عملکرد ساخته نمی‌شود.</p>
        </div>
      )}
    </section>
  );
}

export function ModelOverview({
  model,
  variant,
  onVariant,
}: {
  model: ModelRun;
  variant: ModelVariant;
  onVariant: (variant: ModelVariant) => void;
}) {
  const metric = model.metrics?.[variant];
  const splits = modelSplits(model);
  const nodes = [
    { name: "ورودی خام", value: "۲۱", hint: "ویژگی allowlist" },
    {
      name: "انکدر",
      value: number(model.config.hidden_dim),
      hint:
        variant === "feature"
          ? "بدون پیام‌رسانی"
          : `${number(model.config.layers)} لایهٔ پیام‌رسانی`,
    },
    {
      name: "فضای نهفته",
      value: number(model.config.latent_dim),
      hint: "بردار هر گره",
    },
    {
      name: "دیکدر",
      value: number(model.config.hidden_dim),
      hint: "بازسازی ویژگی",
    },
    { name: "خروجی", value: "۲۱", hint: "ویژگی بازسازی‌شده" },
  ];
  return (
    <>
      <div className="mdl-variant-toolbar">
        <div>
          <h2>
            {model.status === "draft"
              ? "طرح مدل پیش‌نویس"
              : "نمای مدل آموزش‌دیده"}
          </h2>
          <p>مدل مشترک لایهٔ اول؛ سه گونه با تقسیم داده و پروتکل یکسان</p>
        </div>
        <div
          className="mdl-variant-buttons"
          role="group"
          aria-label="گونهٔ نمایش مدل"
        >
          {(["feature", "graph", "spectral"] as ModelVariant[]).map((value) => (
            <button
              key={value}
              aria-pressed={variant === value}
              onClick={() => onVariant(value)}
            >
              {variantLabels[value]}
            </button>
          ))}
        </div>
      </div>
      <section className="mdl-metrics" aria-label="سنجه‌های مدل انتخاب‌شده">
        {[
          {
            label: "MSE بازسازی · آزمون",
            value: metric ? scoreNumber(metric.featureMSE) : "—",
            hint: "خطای بازسازی ویژگی؛ نه دقت تشخیص",
            color: "green",
          },
          {
            label: "بهترین Loss اعتبارسنجی",
            value: metric ? scoreNumber(metric.validationLoss) : "—",
            hint: "هدف ترکیبی با وزن‌های همین مدل",
            color: "blue",
          },
          {
            label: "AUC رابطهٔ نمونه‌شده",
            value: metric ? scoreNumber(metric.relationAUC) : "—",
            hint: "ارزیابی زوج‌های گراف؛ نه تشخیص حمله",
            color: "lilac",
          },
          {
            label: "ویژگی‌های فعال",
            value:
              model.activeFeatures === null
                ? "—"
                : `${number(model.activeFeatures)} از ۲۱`,
            hint: "بر اساس دادهٔ آموزش همین نسخه",
            color: "amber",
          },
        ].map((item) => (
          <div className="mdl-card mdl-metric" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
            <small>{item.hint}</small>
            <i className={item.color} />
          </div>
        ))}
      </section>
      <div className="mdl-overview-grid">
        <LearningCurve model={model} variant={variant} />
        <section className="mdl-card mdl-architecture">
          <div className="mdl-section-heading">
            <div>
              <GitBranch size={17} />
              <div>
                <h2>معماری و ورودی‌ها</h2>
                <p>Layer-1 Masked Autoencoder</p>
              </div>
            </div>
          </div>
          <div className="mdl-architecture-flow">
            {nodes.map((node, index) => (
              <div key={node.name}>
                <span>{node.name}</span>
                <strong>{node.value}</strong>
                <small>{node.hint}</small>
                {index < nodes.length - 1 && (
                  <ArrowLeft size={13} className="mdl-node-arrow" />
                )}
              </div>
            ))}
          </div>
          <div className="mdl-architecture-facts">
            <span>
              Optimizer<strong>Adam</strong>
            </span>
            <span>
              Learning rate<strong dir="ltr">0.001</strong>
            </span>
            <span>
              Seed<strong>{number(model.config.seed)}</strong>
            </span>
          </div>
          <div className="mdl-input-view">
            <Layers3 size={15} />
            <p>
              ویژگی‌های خام با mask اعتبار؛ scaler فقط روی بخش آموزش برازش
              می‌شود. نرمال‌سازی ورودی مدل با صفحهٔ نرمال‌سازی داده یکی نیست. دو
              سر خروجی، بازسازی ویژگی و وجود/وزن رابطه را برآورد می‌کنند.
            </p>
          </div>
        </section>
      </div>
      <div className="mdl-provenance-grid">
        <section className="mdl-card mdl-data-splits">
          <div className="mdl-section-heading">
            <div>
              <Layers3 size={17} />
              <div>
                <h2>تقسیم داده و منشأ</h2>
                <p>
                  {model.status === "draft"
                    ? "پیش‌بررسی ساختاری؛ تقسیم واقعی هنوز انجام نشده"
                    : "تقسیم نمایشی در سطح چانک، نه ردیف تصادفی"}
                </p>
              </div>
            </div>
            <Link to={dayDetailsPath(model.config.day)}>
              روز داده
              <ArrowUpLeft size={13} />
            </Link>
          </div>
          <div className="mdl-split-track">
            {splits.map((split) => (
              <span
                key={split.label}
                style={{ flex: split.count, background: split.color }}
                title={`${split.label}: ${split.count}`}
              />
            ))}
          </div>
          <div className="mdl-split-labels">
            {splits.map((split) => (
              <span key={split.label}>
                <i style={{ background: split.color }} />
                {split.label}
                <strong>{number(split.count)}</strong>
              </span>
            ))}
          </div>
          <dl className="mdl-metadata-list">
            <div>
              <dt>روز آموزش / مرجع</dt>
              <dd>{dateLabel(model.config.day)}</dd>
            </div>
            <div>
              <dt>چانک‌های منبع</dt>
              <dd>{model.graphChunks.map(number).join("، ")}</dd>
            </div>
            <div>
              <dt>نمای ویژگی</dt>
              <dd>
                <bdi>raw_allowlist_v1</bdi>
              </dd>
            </div>
            <div>
              <dt>هویت و lineage واقعی</dt>
              <dd>در این ماک تأیید نشده</dd>
            </div>
          </dl>
        </section>
        <section className="mdl-card mdl-artifacts">
          <div className="mdl-section-heading">
            <div>
              <FileBox size={17} />
              <div>
                <h2>بستهٔ مدل و فایل‌ها</h2>
                <p>شناسهٔ نسخه، تنظیمات و مسیرهای نمایشی</p>
              </div>
            </div>
          </div>
          <div className="mdl-artifact-row">
            <FileBox size={17} />
            <div>
              <strong dir="ltr">{variant}_model.pt</strong>
              <span>
                وزن‌های مدل ·{" "}
                {model.status === "draft"
                  ? "هنوز ساخته نشده"
                  : "نام فایل نمونه، بدون وزن قابل دریافت"}
              </span>
            </div>
            <LockKeyhole size={14} />
          </div>
          <div className="mdl-artifact-row">
            <FileBox size={17} />
            <div>
              <strong dir="ltr">manifest.json</strong>
              <span>کارت مدل JSON از دکمهٔ بالای صفحه قابل دریافت است.</span>
            </div>
          </div>
          <p className="mdl-artifact-note">
            <Info size={13} />
            فایل checkpoint واقعی در این پنل بارگذاری نشده است. همهٔ سنجه‌ها و
            منحنی‌های نسخه‌های ثبت‌شده دادهٔ ثابت ماک‌اند.
          </p>
        </section>
      </div>
    </>
  );
}
