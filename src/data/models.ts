import { mockDays, number } from "./days";

export type ModelFamily = "autoencoder" | "normal-reference";
export type ModelVariant = "feature" | "graph" | "spectral";
export type ModelStatus = "ready" | "archived" | "draft";
export const familyLabels: Record<ModelFamily, string> = {
  autoencoder: "Autoencoder لایهٔ اول",
  "normal-reference": "مدل مرجع رفتار نرمال",
};
export const variantLabels: Record<ModelVariant, string> = {
  feature: "Feature-only",
  graph: "Graph-aware",
  spectral: "Spectral-aware",
};
export const modelStatusLabels: Record<ModelStatus, string> = {
  ready: "ثبت‌شده",
  archived: "آرشیو",
  draft: "پیش‌نویس",
};
export const scorePolicies = [
  "spectral_reconstruction",
  "graph_reconstruction",
  "feature_reconstruction",
  "feature_spectral_gap",
  "feature_graph_gap",
  "joint_spectral_gap",
] as const;

export const numericFields = [
  {
    key: "epochs",
    label: "تعداد دوره‌ها",
    hint: "از ۱ تا ۱۰۰۰؛ تعداد دورهٔ کامل آموزش",
    min: 1,
    max: 1000,
    step: 1,
    group: "training",
  },
  {
    key: "hidden_dim",
    label: "بعد لایهٔ پنهان",
    hint: "بزرگ‌تر از latent و حداکثر ۲۵۶",
    min: 3,
    max: 256,
    step: 1,
    group: "architecture",
  },
  {
    key: "latent_dim",
    label: "بعد فضای نهفته",
    hint: "از ۲ تا ۲۰؛ کمتر از بعد پنهان",
    min: 2,
    max: 20,
    step: 1,
    group: "architecture",
  },
  {
    key: "layers",
    label: "تعداد لایهٔ پیام‌رسانی",
    hint: "از ۱ تا ۶؛ گونهٔ feature پیام‌رسانی ندارد",
    min: 1,
    max: 6,
    step: 1,
    group: "architecture",
  },
  {
    key: "max_pairs",
    label: "بودجهٔ زوج‌های رابطه",
    hint: "از ۱ تا ۸۱۹۲؛ حداکثر زوج‌های نمونه",
    min: 1,
    max: 8192,
    step: 1,
    group: "training",
  },
  {
    key: "structure_weight",
    label: "وزن loss ساختار",
    hint: "از ۰ تا ۱۰؛ در مرجع نرمال ثابت است",
    min: 0,
    max: 10,
    step: 0.01,
    group: "loss",
  },
  {
    key: "weight_loss_weight",
    label: "وزن loss وزن یال",
    hint: "از ۰ تا ۱۰؛ در مرجع نرمال ثابت است",
    min: 0,
    max: 10,
    step: 0.01,
    group: "loss",
  },
  {
    key: "seed",
    label: "بذر تصادفی",
    hint: "عدد صحیح از ۰ تا ۴۲۹۴۹۶۷۲۹۵",
    min: 0,
    max: 4294967295,
    step: 1,
    group: "training",
  },
  {
    key: "alpha",
    label: "سهم اسمی دُم بالایی (α)",
    hint: "بین صفر و یک؛ تضمین نرخ خطای عملیاتی نیست",
    min: 0,
    max: 1,
    step: 0.001,
    group: "reference",
  },
] as const;
export type NumericParameter = (typeof numericFields)[number]["key"];
export type NumericParameters = Record<NumericParameter, number>;
export interface ModelConfig extends NumericParameters {
  family: ModelFamily;
  day: string;
  evaluate_days: string[];
  score_policy: (typeof scorePolicies)[number];
}
export const defaultNumericParameters: NumericParameters = {
  epochs: 60,
  hidden_dim: 64,
  latent_dim: 16,
  layers: 2,
  max_pairs: 2048,
  structure_weight: 0.1,
  weight_loss_weight: 0.05,
  seed: 17,
  alpha: 0.01,
};
export interface ModelEditor {
  baseId: string;
  family: ModelFamily;
  day: string;
  evaluateDays: string[];
  policy: (typeof scorePolicies)[number];
  fields: Record<NumericParameter, string>;
}
export type ModelErrors = Partial<
  Record<NumericParameter | "day" | "evaluate_days", string>
>;
export interface VariantMetrics {
  featureMSE: number;
  validationLoss: number;
  relationAUC: number;
  baselineMSE: number;
  selectedEpoch: number;
}
export interface BehaviorReference {
  id: string;
  calibrationNodes: number;
  evaluationDay: string;
  evaluatedNodes: number;
  validNodes: number;
  flaggedNodes: number;
  threshold: number;
  signals: { name: string; valid: number; total: number }[];
}
export interface ModelRun {
  id: string;
  version: string;
  title: string;
  status: ModelStatus;
  config: ModelConfig;
  baseId: string | null;
  createdAt: string;
  metrics: Record<ModelVariant, VariantMetrics> | null;
  reference: BehaviorReference | null;
  activeFeatures: number | null;
  graphChunks: number[];
}

const metrics = (offset = 0): Record<ModelVariant, VariantMetrics> => ({
  feature: {
    featureMSE: 0.219 + offset,
    validationLoss: 0.239 + offset,
    relationAUC: 0.73 - offset,
    baselineMSE: 0.263,
    selectedEpoch: 45,
  },
  graph: {
    featureMSE: 0.176 + offset,
    validationLoss: 0.204 + offset,
    relationAUC: 0.84 - offset,
    baselineMSE: 0.263,
    selectedEpoch: 49,
  },
  spectral: {
    featureMSE: 0.154 + offset,
    validationLoss: 0.181 + offset,
    relationAUC: 0.871 - offset,
    baselineMSE: 0.263,
    selectedEpoch: 47,
  },
});
const config = (
  family: ModelFamily,
  day: string,
  evaluate_days: string[] = [],
): ModelConfig => ({
  ...defaultNumericParameters,
  family,
  day,
  evaluate_days,
  score_policy: "joint_spectral_gap",
});
// All registry entries, scores, reference data and checkpoint names are fixtures.
export const mockModelRuns: ModelRun[] = [
  {
    id: "mock-normal-model-v3",
    version: "v0.3",
    title: "مرجع نرمال · انکدر مشترک L1",
    status: "ready",
    config: config("normal-reference", "2026-10-31", [
      "2026-11-03",
      "2026-11-04",
    ]),
    baseId: null,
    createdAt: "2026-11-05T07:10:00Z",
    metrics: metrics(),
    activeFeatures: 19,
    graphChunks: [0, 1, 2, 3, 4, 5, 6, 7],
    reference: {
      id: "mock-normal-reference-v3",
      calibrationNodes: 1200,
      evaluationDay: "2026-11-03",
      evaluatedNodes: 4500,
      validNodes: 3600,
      flaggedNodes: 84,
      threshold: 0.317,
      signals: [
        { name: "بازسازی ویژگی‌ها", valid: 4320, total: 4500 },
        { name: "شکاف طیفی", valid: 3900, total: 4500 },
        { name: "ساختار گراف", valid: 4110, total: 4500 },
        { name: "اشتراک معتبر سیاست", valid: 3600, total: 4500 },
      ],
    },
  },
  {
    id: "mock-l1-autoencoder-v2",
    version: "v0.2",
    title: "Autoencoder مشترک · روز ۱۲ آبان",
    status: "ready",
    config: config("autoencoder", "2026-11-03"),
    baseId: null,
    createdAt: "2026-11-04T06:35:00Z",
    metrics: metrics(0.012),
    reference: null,
    activeFeatures: 18,
    graphChunks: [0, 1, 2, 3, 4, 5, 6, 7],
  },
  {
    id: "mock-normal-model-v1",
    version: "v0.1",
    title: "مرجع نرمال · نسخهٔ پیشین",
    status: "archived",
    config: config("normal-reference", "2026-11-02", ["2026-11-04"]),
    baseId: null,
    createdAt: "2026-11-03T08:20:00Z",
    metrics: metrics(0.025),
    reference: null,
    activeFeatures: 17,
    graphChunks: [0, 1, 2, 3, 4, 5, 6, 7],
  },
];

export function editorFromModel(model: ModelRun): ModelEditor {
  return {
    baseId: model.id,
    family: model.config.family,
    day: model.config.day,
    evaluateDays: [...model.config.evaluate_days],
    policy: model.config.score_policy,
    fields: Object.fromEntries(
      numericFields.map((field) => [
        field.key,
        String(model.config[field.key]),
      ]),
    ) as ModelEditor["fields"],
  };
}
export function availableGraphChunks(day: string) {
  return (
    mockDays
      .find((item) => item.date === day)
      ?.chunks.filter((chunk) => chunk.completedStages >= 3)
      .map((chunk) => chunk.index) ?? []
  );
}

export function validateModelEditor(editor: ModelEditor): {
  errors: ModelErrors;
  config: ModelConfig | null;
} {
  const errors: ModelErrors = {};
  const parsed = { ...defaultNumericParameters };
  for (const field of numericFields) {
    if (
      (field.key === "alpha" && editor.family === "autoencoder") ||
      (field.group === "loss" && editor.family === "normal-reference")
    )
      continue;
    const raw = editor.fields[field.key].trim();
    const value = Number(raw);
    parsed[field.key] = value;
    if (
      !raw ||
      !Number.isFinite(value) ||
      (field.step === 1 && !Number.isInteger(value)) ||
      value < field.min ||
      value > field.max ||
      (field.key === "alpha" && (value <= 0 || value >= 1))
    ) {
      errors[field.key] =
        field.key === "alpha"
          ? "α باید بزرگ‌تر از صفر و کوچک‌تر از یک باشد."
          : `${field.label} باید ${field.step === 1 ? "عدد صحیح " : "عددی "}بین ${number(field.min)} و ${number(field.max)} باشد.`;
    }
  }
  if (
    !errors.hidden_dim &&
    !errors.latent_dim &&
    parsed.hidden_dim <= parsed.latent_dim
  )
    errors.hidden_dim = "بعد پنهان باید بزرگ‌تر از بعد نهفته باشد.";
  const minimum = editor.family === "normal-reference" ? 4 : 3;
  if (availableGraphChunks(editor.day).length < minimum)
    errors.day = `حداقل ${number(minimum)} گراف چانک آماده برای این مسیر لازم است.`;
  if (
    editor.family === "normal-reference" &&
    (!editor.evaluateDays.length ||
      editor.evaluateDays.includes(editor.day) ||
      editor.evaluateDays.some(
        (day) => !mockDays.some((item) => item.date === day),
      ))
  )
    errors.evaluate_days =
      "حداقل یک روز ارزیابی مستقل از روز مرجع انتخاب کنید.";
  if (Object.keys(errors).length) return { errors, config: null };
  return {
    errors,
    config: {
      ...parsed,
      family: editor.family,
      day: editor.day,
      evaluate_days:
        editor.family === "normal-reference"
          ? [...editor.evaluateDays].sort()
          : [],
      score_policy:
        editor.family === "normal-reference"
          ? editor.policy
          : "joint_spectral_gap",
    },
  };
}

export function previewRequest(config: ModelConfig) {
  const common = {
    epochs: config.epochs,
    hidden_dim: config.hidden_dim,
    latent_dim: config.latent_dim,
    layers: config.layers,
    max_pairs: config.max_pairs,
    seed: config.seed,
  };
  return config.family === "autoencoder"
    ? {
        method: "POST",
        endpoint: "/api/v1/actions/learning/train-layer1-autoencoder/",
        parameters: {
          ...common,
          day: config.day,
          structure_weight: config.structure_weight,
          weight_loss_weight: config.weight_loss_weight,
          force: false,
        },
      }
    : {
        method: "POST",
        endpoint: "/api/v1/actions/behavior/learn-normal/",
        parameters: {
          ...common,
          normal_day: config.day,
          evaluate_days: config.evaluate_days,
          alpha: config.alpha,
          score_policy: config.score_policy,
          origin_id_field: "artificial_day.original_id",
        },
      };
}

export function modelSplits(model: ModelRun) {
  const n = model.graphChunks.length;
  if (!n) return [];
  const reference = model.config.family === "normal-reference";
  const train = reference
    ? Math.min(n - 3, Math.max(1, Math.floor(0.6 * n)))
    : Math.max(1, Math.floor(0.6 * n));
  const validation = reference
    ? Math.min(n - train - 2, Math.max(1, Math.floor(0.15 * n)))
    : Math.max(1, Math.floor(0.2 * n));
  const calibration = reference
    ? Math.max(1, Math.floor((n - train - validation) / 2))
    : 0;
  return [
    { label: "آموزش", count: train, color: "var(--chart-green)" },
    { label: "اعتبارسنجی", count: validation, color: "var(--chart-blue)" },
    ...(reference
      ? [
          {
            label: "کالیبراسیون",
            count: calibration,
            color: "var(--chart-lilac)",
          },
        ]
      : []),
    {
      label: "آزمون",
      count: n - train - validation - calibration,
      color: "var(--chart-amber)",
    },
  ];
}
export function lossHistory(model: ModelRun, variant: ModelVariant) {
  const metric = model.metrics?.[variant];
  if (!metric) return [];
  return Array.from({ length: model.config.epochs }, (_, index) => {
    const epoch = index + 1;
    return {
      epoch,
      train: 0.11 + 0.6 * Math.exp(-epoch / 12),
      validation:
        metric.validationLoss +
        0.56 * (Math.exp(-epoch / 10) - Math.exp(-metric.selectedEpoch / 10)) +
        (epoch > metric.selectedEpoch
          ? (epoch - metric.selectedEpoch) * 0.0012
          : (metric.selectedEpoch - epoch) * 0.0003),
    };
  });
}
export const scoreNumber = (value: number, digits = 3) =>
  new Intl.NumberFormat("fa-IR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
export function downloadModelJSON(filename: string, value: object) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], {
      type: "application/json;charset=utf-8",
    }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
