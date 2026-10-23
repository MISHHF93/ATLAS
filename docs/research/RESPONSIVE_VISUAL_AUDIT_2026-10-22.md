# Responsive visual audit — October 22, 2026

The running production build was checked across all 16 canonical pages at
1440×900 and 390×844, plus the Real time viewer at 1920×1080, 1440×900,
1280×720, 1024×768, 768×1024, 390×844 and 844×390.

## Repairs

- Removed fixed 600/760-pixel viewer heights and the viewport-minus-260-pixel
  assumption. A ResizeObserver measures available main-panel space, accounting
  for the instrument controls, surrounding content, footer and browser viewport.
  A font-relative minimum preserves usability on very short screens, where the
  page remains scrollable.
- The trade chart and model input panel use container queries: they sit beside
  one another when width or landscape proportions allow and stack otherwise.
  The Real time view no longer spends space on a separate TradingView ticker.
- Model candle rendering measures its own width, adjusts how many recent input
  candles are visible, and retains readable price/time labels. This changes the
  rendering window, not the observer's training inputs or feature lookbacks.
- Tablet layouts flow down the document so the risk panel cannot cover chart
  controls. Mobile navigation uses a horizontal rail rather than consuming most
  of the screen height; the active link is brought into horizontal view only.
- Markets now has a viewport-sized flex shell and an actual scrolling content
  region. Role headings wrap instead of clipping. Small-screen card headers wrap
  and wide tables can scroll inside their cards.
- Model input candles appear ahead of the longer explanatory text. Independent
  model-panel scrolling and stable reading positions are preserved during updates.

## Evidence

All 32 canonical-page checks returned HTTP 200, with one active navigation item,
no document horizontal overflow, and no browser page errors. Real time controls
were clickable at every tested size. Viewer bounds stayed inside the desktop
main panel; trade canvas heights ranged from 158 to 724 pixels as space changed.
Scroll positions stayed within two pixels across live refreshes. The mobile
Markets content region was verified to scroll beyond the first screen.

The final live API check reported `public_last_trade`, a connected feed, 370
learned observer outcomes and approximately 0.21 seconds since the last received
trade. These are point-in-time observations, not latency or accuracy guarantees.
The experimental observer and its data boundaries are unchanged by this work.

Frontend type checking, production build, route regression checks and whitespace
checks passed. Screenshots and geometry results are saved locally under
`.test-runs/visual-audit/responsive-final/`. Backend code was not changed.
