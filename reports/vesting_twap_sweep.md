# Vesting TWAP margin sweep

Rectangular end-of-window pump: the last `duration` hours of a `window`-hour
TWAP sit at `k × p_entry`, the rest of the window sits at `p_entry`.
Unlocked fraction is `engine.vesting.unlocked_fraction(0, t=t0, …)` so only
`u_price = ln(TWAP / p_entry) / ln(M)` contributes (defaults: M=5).

Cells in the **1h** table are **bold** when the unlocked fraction is ≥ 5%.
Defaults are not changed by this report (D14 stays a Claude decision).

## Pump duration 0.5h

| k \\ window | 6h | 12h | 24h | 36h |
| --- | --- | --- | --- | --- |
| 2× | 0.0497 | 0.0254 | 0.0128 | 0.0086 |
| 2.5× | 0.0732 | 0.0377 | 0.0191 | 0.0128 |
| 3× | 0.0958 | 0.0497 | 0.0254 | 0.0170 |
| 3.1× | 0.1002 | 0.0521 | 0.0266 | 0.0179 |
| 3.5× | 0.1176 | 0.0616 | 0.0315 | 0.0212 |
| 4× | 0.1386 | 0.0732 | 0.0377 | 0.0254 |

## Pump duration 1h (cells ≥ 5% marked)

| k \\ window | 6h | 12h | 24h | 36h |
| --- | --- | --- | --- | --- |
| 2× | **0.0958** | 0.0497 | 0.0254 | 0.0170 |
| 2.5× | **0.1386** | **0.0732** | 0.0377 | 0.0254 |
| 3× | **0.1787** | **0.0958** | 0.0497 | 0.0336 |
| 3.1× | **0.1865** | **0.1002** | **0.0521** | 0.0352 |
| 3.5× | **0.2164** | **0.1176** | **0.0616** | 0.0417 |
| 4× | **0.2519** | **0.1386** | **0.0732** | 0.0497 |

## Pump duration 2h

| k \\ window | 6h | 12h | 24h | 36h |
| --- | --- | --- | --- | --- |
| 2× | 0.1787 | 0.0958 | 0.0497 | 0.0336 |
| 2.5× | 0.2519 | 0.1386 | 0.0732 | 0.0497 |
| 3× | 0.3174 | 0.1787 | 0.0958 | 0.0655 |
| 3.1× | 0.3297 | 0.1865 | 0.1002 | 0.0686 |
| 3.5× | 0.3766 | 0.2164 | 0.1176 | 0.0808 |
| 4× | 0.4307 | 0.2519 | 0.1386 | 0.0958 |

## Smallest window that keeps a 1h pump under 5%

- 1h 3.1×: **36h** is the smallest window in the grid (unlocked fraction 0.0352 < 5%).
- 1h 3.5×: **36h** is the smallest window in the grid (unlocked fraction 0.0417 < 5%).

A 1h 3× pump on the current 24h default is 0.0497, just under 5%. A 1h 3.1× or 3.5× pump needs the 36h window; 24h is not enough.
