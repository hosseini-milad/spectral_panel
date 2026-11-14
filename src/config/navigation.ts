import {
  LayoutDashboard,
  CalendarDays,
  Workflow,
  ListTodo,
  ChartNoAxesCombined,
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
    description: "مشاهدهٔ اجرای فعال، جایگاه صف انتظار و وضعیت worker.",
  },
  {
    path: "/visualizations",
    label: "گزارش",
    group: "analysis",
    icon: ChartNoAxesCombined,
    description: "مرور فرامولفه‌ها، مولفه‌ها و جزئیات مشاهدات تا دادهٔ اصلی.",
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
    description: "تنظیمات عمومی، کلیدها، وب‌هوک‌ها، امنیت و اعلان‌های نمونه.",
  },
] as const;

export type NavigationItem = (typeof navigation)[number];
export const navigationGroups = [
  { id: "workspace", label: "فضای کار" },
  { id: "analysis", label: "تحلیل و پردازش" },
  { id: "system", label: "مدیریت" },
] as const;
