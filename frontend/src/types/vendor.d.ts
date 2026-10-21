declare module "lightweight-charts" {
  export interface IChartApi {
    addCandlestickSeries(options?: Record<string, unknown>): ISeriesApi;
    addHistogramSeries(options?: Record<string, unknown>): ISeriesApi;
    addLineSeries(options?: Record<string, unknown>): ISeriesApi;
    timeScale(): { fitContent(): void };
    remove(): void;
  }
  export interface ISeriesApi {
    setData(data: unknown[]): void;
    update(bar: unknown): void;
    createPriceLine(options?: Record<string, unknown>): void;
  }
  export function createChart(container: HTMLElement, options?: Record<string, unknown>): IChartApi;
}

declare module "lucide-react" {
  import type { SVGProps } from "react";
  export type LucideIcon = (props: SVGProps<SVGSVGElement> & { size?: number | string }) => JSX.Element;
  export const Activity: LucideIcon;
  export const Wifi: LucideIcon;
  export const ShieldCheck: LucideIcon;
  export const AlertTriangle: LucideIcon;
}

