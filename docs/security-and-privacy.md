# Security And Privacy

`stock-analysis-plus` is a public-safe extraction of stock research workflow primitives. It should not contain private operating data.

## Not Committed

- API keys, broker credentials, market-data tokens, or webhook secrets.
- Local databases, run bundles, generated reports, screenshots, or logs.
- Personal watchlists, account positions, order data, or trading history.
- Browser profiles, sessions, cookies, or social-account captures.
- Machine-local paths or private source repository paths.

## Local Configuration

Use environment variables or a private `.env` file for any live provider configuration. Keep `.env`, output folders, and local run artifacts out of git.

## Operational Boundary

The repository is for research workflow automation and software demonstration. It does not place trades, change brokerage accounts, or provide financial advice.
