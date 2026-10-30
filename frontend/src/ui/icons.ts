import {
  Activity, BookOpen, CandlestickChart, Database, FlaskConical, Gauge, HeartPulse, Landmark, Newspaper, Settings, type LucideIcon,
} from "lucide-react";
import type { PageId } from "../nav/nav.config";

const PAGE_ICONS: Record<PageId, LucideIcon> = {
  home: Gauge, markets: CandlestickChart, predictions: FlaskConical, news: Newspaper, account: Activity,
  money: Landmark, data: Database, health: HeartPulse, settings: Settings,
};

export const pageIcon = (id: PageId): LucideIcon => PAGE_ICONS[id] ?? BookOpen;
