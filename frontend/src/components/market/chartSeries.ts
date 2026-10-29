/** Lightweight Charts requires strictly increasing, unique numeric timestamps.
 * Multiple predictions may legitimately share a candle. Only the display series
 * is collapsed: the last point supplied for a time wins, without shifting time
 * or changing its value. Prediction records and markers remain separate.
 */
export function orderedChartPoints<T extends { time: number }>(points: readonly T[]): T[] {
  const byTime = new Map<number, T>();
  for (const point of points) {
    if (Number.isFinite(point.time)) byTime.set(point.time, point);
  }
  return [...byTime.values()].sort((a, b) => a.time - b.time);
}
