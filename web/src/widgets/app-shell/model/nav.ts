import {
  Activity,
  BookOpen,
  Database,
  Filter,
  FlaskConical,
  LayoutList,
  Newspaper,
  Search,
  Settings,
  Sparkle,
  UserRound,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { ru } from "@/shared/i18n/ru";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Вторая клавиша последовательности `g …`. */
  goKey?: string;
  /** Показывать в нижней панели на узком экране. */
  primary?: boolean;
};

export const NAV: NavItem[] = [
  { href: "/", label: ru.nav.digest, icon: Newspaper, goKey: "d", primary: true },
  { href: "/tenders", label: ru.nav.tenders, icon: LayoutList, goKey: "c", primary: true },
  { href: "/search", label: ru.nav.search, icon: Search, primary: true },
  { href: "/filters", label: ru.nav.filters, icon: Filter, goKey: "f", primary: true },
  { href: "/research", label: ru.nav.research, icon: FlaskConical, goKey: "i" },
  { href: "/data", label: ru.nav.data, icon: Database, goKey: "n" },
  { href: "/recommendations", label: ru.nav.recommendations, icon: Sparkle, goKey: "r", primary: true },
  { href: "/profile", label: ru.nav.profile, icon: UserRound },
  { href: "/monitoring", label: ru.nav.monitoring, icon: Activity, goKey: "m" },
  { href: "/settings", label: ru.nav.settings, icon: Settings },
  { href: "/help", label: ru.nav.help, icon: BookOpen },
];
