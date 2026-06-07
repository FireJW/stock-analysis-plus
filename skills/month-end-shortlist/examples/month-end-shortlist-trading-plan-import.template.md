## Trading Plan Text Import

Paste a prior chat trading plan, Markdown table, or plain-text watch plan into a
`.md` or `.txt` file and pass it through `--trading-plan-result`.

```powershell
financial-analysis\skills\month-end-shortlist\scripts\run_local_stock_pool_manager.cmd `
  --trading-plan-result .tmp\latest-trading-plan.md `
  --output-dir .tmp\local-stock-pool-manager-from-chat-plan `
  --target-date 2026-05-11
```

Supported line shapes:

| Name | State | Action |
|---|---|---|
| 光迅科技 `002281.SZ` | 已触发 | 等回踩 153.47 不破；失效：跌破 146.16；压力 160.00 / 166.00 |
| 东山精密 `002384.SZ` | 未确认 | 站上 196.00 前只观察；失效：跌破 188.00 |

The importer keeps these entries as local workflow input. It does not mutate a
broker watchlist, alert list, or any account-side object.
