# Stock Analysis Plus

Public-safe stock analysis workflow kit extracted from a larger private research workspace.

This repository packages reusable Python workflows for:

- month-end stock shortlist generation
- macro health overlays for candidate review
- Longbridge market-data adapters
- evidence bundle and decision-report helpers

The extraction intentionally omits private handoffs, browser profiles, session logs, personal paths, live credentials, and generated research artifacts. Examples are templates only.

## Repository Layout

```text
skills/
  longbridge/              Longbridge CLI/SDK adapters and references
  macro-health-overlay/    Macro overlay runner and public request template
  month-end-shortlist/     Stock pool, evidence bundle, shortlist, and report scripts
docs/
  index.html               GitHub Pages portfolio homepage
stock_analysis_plus/
  cli.py                   Lightweight inventory CLI
```

## Quick Start

```powershell
py -3 -m stock_analysis_plus.cli list
py -3 skills\month-end-shortlist\scripts\month_end_shortlist.py --help
py -3 skills\macro-health-overlay\scripts\macro_health_overlay.py --help
```

Some workflows can use live market-data tools when configured locally. No API keys are committed or required for repository inspection.

## Public Safety

This repo is a new repository with new Git history. It is not a fork and does not contain:

- `.ai/`, `.claude/`, recovered artifacts, or rollout logs
- browser profile files or cookies
- personal Windows paths or vault paths
- private API keys or tokens
- generated spreadsheets, reports, screenshots, or live research outputs

## Attribution

Source material was extracted from a local fork of the Apache-2.0 licensed `anthropics/financial-services` ecosystem and then reduced into a public-safe stock-analysis subset.
