import {
  Activity, BarChart3, BookOpen, Bot, Building2, CandlestickChart, ClipboardCheck, Database, FileSearch, FileText, FlaskConical,
  Gauge, Home, Inbox, KeyRound, Landmark, Layers, LineChart, ListChecks, Map, Network, PiggyBank, Receipt, ScrollText, Settings,
  ShieldCheck, Sigma, TrendingUp, UserCheck, Wallet, type LucideIcon,
} from "lucide-react";
import type { PageGroupId } from "../components/shell/pagesMap";

export const SECTION_ICONS: Record<PageGroupId, LucideIcon> = {
  home: Home, trade: TrendingUp, money: Landmark, research: FlaskConical, compliance: ShieldCheck, settings: Settings,
};

const PAGE_ICONS: Record<string, LucideIcon> = {
  overview: Gauge, inbox: Inbox, desk: CandlestickChart, listings: Building2, depth: Layers, positions: ListChecks, account: Activity,
  autopilot: Bot, rulebook: ScrollText, audit: ClipboardCheck, identity: UserCheck, "chart-read": LineChart, "price-action": BarChart3,
  "walk-forward": Sigma, training: FlaskConical, "prediction-ledger": FileText, evidence: FileSearch, bars: Database, connectors: Network,
  reserve: PiggyBank, capability: Map, specs: BookOpen, money: Landmark, payments: Receipt, portal: Wallet, tax: Receipt,
  compliance: ShieldCheck, "api-keys": KeyRound,
  risk: Activity, models: FileSearch, settings: Settings, docs: BookOpen, data: Database, research: LineChart,
};

export const pageIcon = (id: string): LucideIcon => PAGE_ICONS[id] ?? FileText;
