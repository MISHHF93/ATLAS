export const ColorType = {
  Solid: "solid",
  VerticalGradient: "gradient",
} as const;

export const CrosshairMode = {
  Normal: 0,
  Magnet: 1,
} as const;

export const LineStyle = {
  Solid: 0,
  Dotted: 1,
  Dashed: 2,
  LargeDashed: 3,
  SparseDotted: 4,
} as const;

export interface CandlestickBarData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface LinePointData {
  time: number;
  value: number;
}

export interface PriceLineOptions {
  price: number;
  color: string;
  lineWidth?: number;
  lineStyle?: number;
  axisLabelVisible?: boolean;
  title?: string;
}

export interface ChartOptions {
  width?: number;
  height?: number;
  layout?: Record<string, unknown>;
  grid?: Record<string, unknown>;
  crosshair?: Record<string, unknown>;
  rightPriceScale?: Record<string, unknown>;
  timeScale?: Record<string, unknown>;
}

export function createChart(container: HTMLElement, options: ChartOptions = {}) {
  const canvas = document.createElement("canvas");
  const width = options.width || container.clientWidth || 720;
  const height = options.height || container.clientHeight || 220;
  canvas.width = width;
  canvas.height = height;
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  canvas.style.display = "block";
  container.innerHTML = "";
  container.appendChild(canvas);

  let candleData: CandlestickBarData[] = [];
  const priceLines: PriceLineOptions[] = [];
  const lineSeriesList: Array<{ opts: Record<string, unknown>; data: LinePointData[] }> = [];

  function renderCanvas(): void {
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    if (!candleData || candleData.length === 0) return;

    const prices: number[] = [];
    for (const c of candleData) {
      prices.push(c.high, c.low);
    }
    for (const pl of priceLines) {
      if (typeof pl.price === "number") prices.push(pl.price);
    }
    for (const ls of lineSeriesList) {
      for (const pt of ls.data) {
        if (typeof pt.value === "number") prices.push(pt.value);
      }
    }

    const minP = Math.min(...prices);
    const maxP = Math.max(...prices);
    const span = Math.max(0.0001, maxP - minP);
    const toY = (p: number): number => h - 14 - ((p - minP) / span) * (h - 28);
    const stepX = Math.max(4, (w - 80) / Math.max(1, candleData.length));

    for (const pl of priceLines) {
      const y = toY(pl.price);
      ctx.save();
      ctx.strokeStyle = pl.color || "#38bdf8";
      ctx.lineWidth = pl.lineWidth || 1;
      if (pl.lineStyle === LineStyle.Dashed) ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(8, y);
      ctx.lineTo(w - 8, y);
      ctx.stroke();
      ctx.restore();
    }

    candleData.forEach((c, idx) => {
      const x = 16 + idx * stepX;
      const isUp = c.close >= c.open;
      const color = isUp ? "#10b981" : "#f43f5e";
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(x, toY(c.high));
      ctx.lineTo(x, toY(c.low));
      ctx.stroke();

      const topY = toY(Math.max(c.open, c.close));
      const botY = toY(Math.min(c.open, c.close));
      const bodyH = Math.max(2, botY - topY);
      ctx.fillRect(x - Math.max(2, stepX * 0.3), topY, Math.max(4, stepX * 0.6), bodyH);
    });
  }

  return {
    addCandlestickSeries(_opts?: Record<string, unknown>) {
      return {
        setData(data: CandlestickBarData[]) {
          candleData = Array.isArray(data) ? data.slice() : [];
          renderCanvas();
        },
        update(bar: CandlestickBarData) {
          if (!bar) return;
          if (candleData.length > 0 && candleData[candleData.length - 1].time === bar.time) {
            candleData[candleData.length - 1] = bar;
          } else {
            candleData.push(bar);
          }
          renderCanvas();
        },
        createPriceLine(opts: PriceLineOptions) {
          const lineObj = { ...opts };
          priceLines.push(lineObj);
          renderCanvas();
          return lineObj;
        },
        removePriceLine(lineObj: unknown) {
          const idx = priceLines.indexOf(lineObj as PriceLineOptions);
          if (idx >= 0) priceLines.splice(idx, 1);
          renderCanvas();
        },
      };
    },
    addLineSeries(opts: Record<string, unknown> = {}) {
      const series = {
        opts,
        data: [] as LinePointData[],
        setData(data: LinePointData[]) {
          series.data = Array.isArray(data) ? data.slice() : [];
          renderCanvas();
        },
        update(pt: LinePointData) {
          series.data.push(pt);
          renderCanvas();
        },
      };
      lineSeriesList.push(series);
      return series;
    },
    timeScale() {
      return {
        fitContent() {
          renderCanvas();
        },
      };
    },
    applyOptions(nextOpts: { width?: number; height?: number } = {}) {
      if (nextOpts.width) canvas.width = nextOpts.width;
      if (nextOpts.height) canvas.height = nextOpts.height;
      renderCanvas();
    },
    remove() {
      if (canvas.parentNode) {
        canvas.parentNode.removeChild(canvas);
      }
    },
  };
}

