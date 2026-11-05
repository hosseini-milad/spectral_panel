import {
  LayoutDashboard,
  CalendarDays,
  Database,
  Workflow,
  ListTodo,
  ChartNoAxesCombined,
  Files,
  BrainCircuit,
  Settings2,
} from "lucide-react";

export const navigation = [
  {
    path: "/",
    label: "نمای کلی",
    group: "workspace",
    icon: LayoutDashboard,
    description: "وضعیت کلی داده‌ها و مراحل پردازش در یک نگاه.",
  },
  {
    path: "/days",
    label: "روزها و چانک‌ها",
    group: "workspace",
    icon: CalendarDays,
    description: "انتخاب روز و چانک، بررسی پوشش داده و مراحل پردازش.",
  },
  {
    path: "/data",
    label: "مرور داده‌ها",
    group: "workspace",
    icon: Database,
    description: "جست‌وجو، فیلتر و مشاهدهٔ جزئیات داده‌ها.",
  },
  {
    path: "/operations",
    label: "عملیات و پردازش",
    group: "analysis",
    icon: Workflow,
    description: "مدیریت مسیر پردازش از ورود داده تا تحلیل طیفی و یادگیری.",
  },
  {
    path: "/jobs",
    label: "صف اجراها",
    group: "analysis",
    icon: ListTodo,
    description: "پیگیری وضعیت اجراها، پارامترها، لاگ‌ها و خطاها.",
  },
  {
    path: "/visualizations",
    label: "تصویر و نمودار",
    group: "analysis",
    icon: ChartNoAxesCombined,
    description: "درخواست نمودار برای انتخاب فعلی و مرور خروجی‌های پیشین.",
  },
  {
    path: "/reports",
    label: "گزارش‌ها",
    group: "analysis",
    icon: Files,
    description: "بررسی و مقایسهٔ نتایج از سطح روز تا گره و فرامولفه.",
  },
  {
    path: "/models",
    label: "مدل و رفتار",
    group: "analysis",
    icon: BrainCircuit,
    description:
      "وضعیت مدل‌ها، مرجع نرمال، پوشش سیگنال‌ها و انحراف‌های رفتاری.",
  },
  {
    path: "/settings",
    label: "تنظیمات",
    group: "system",
    icon: Settings2,
    description: "تنظیمات پنل و سیاست‌های دسترسی در مراحل بعدی توسعه.",
  },
] as const;

export type NavigationItem = (typeof navigation)[number];
export const navigationGroups = [
  { id: "workspace", label: "فضای کار" },
  { id: "analysis", label: "تحلیل و پردازش" },
  { id: "system", label: "مدیریت" },
] as const;
