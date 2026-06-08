# Demo Run

This demo uses the checked-in public macro overlay request template. It can run without committed credentials and writes local outputs under `.tmp/`.

## Command

```powershell
py -3 skills\macro-health-overlay\scripts\macro_health_overlay.py `
  skills\macro-health-overlay\examples\macro-health-overlay-public-mix.request.template.json `
  --output .tmp\demo\macro-health-overlay.result.json `
  --markdown-output .tmp\demo\macro-health-overlay.report.md
```

## Sample Result Shape

```json
{
  "request": {
    "live_data_provider": "public_macro_mix",
    "integration_mode": "advisory_only"
  },
  "macro_health_overlay": {
    "health_label": "mixed_or_neutral_window",
    "risk_posture": "neutral_selective",
    "window_state": "mixed_window",
    "confidence": "low",
    "takeaway": "The macro backdrop is mixed, so downstream screening should stay selective and rely on hard catalysts."
  },
  "scorecard": {
    "primary_trigger_score": 0.0,
    "confirmation_score": 0.0,
    "control_score": 0.0,
    "total_score": 0.0
  }
}
```

## Expected Artifacts

```text
.tmp/demo/
|-- macro-health-overlay.result.json
`-- macro-health-overlay.report.md
```

## Public Boundary

Live public macro sources may be unavailable in a restricted network. In that case the result can report `status: partial` and low confidence while still preserving the workflow contract. Generated outputs stay ignored under `.tmp/` and should not be committed.
