#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from direction_risk_register_runtime import (  # noqa: E402
    DEFAULT_RESTRICTION_DAYS,
    HISTORY_LIMIT,
    apply_direction_risk_to_package,
    direction_risk_level,
    elevated_directions,
    empty_register,
    load_register,
    render_risk_register_markdown,
    restricted_directions,
    risk_summary,
    save_register,
    update_register,
)


def _postclose(direction_key: str, *, status: str, overheat: bool = False,
               divergence: bool = False) -> dict:
    momentum = {
        "direction_key": direction_key,
        "momentum_status": status,
        "overheat": overheat,
        "divergence_dampener": divergence,
    }
    payload = {"direction_momentum": [momentum]}
    if divergence:
        payload["direction_divergence_warnings"] = [{
            "direction_key": direction_key,
            "warning_type": "high_beta_lagging",
        }]
    return payload


class EmptyRegisterTests(unittest.TestCase):
    def test_empty_register_has_required_keys(self) -> None:
        reg = empty_register()
        self.assertEqual(reg["schema_version"], "direction_risk_register/v1")
        self.assertEqual(reg["directions"], {})
        self.assertIn("last_updated", reg)

    def test_load_register_creates_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            reg = load_register(path)
            self.assertEqual(reg["directions"], {})
            self.assertEqual(reg["schema_version"], "direction_risk_register/v1")

    def test_save_then_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "register.json"
            reg = empty_register()
            reg["directions"]["AI算力"] = {"current_status": "elevated"}
            save_register(reg, path)
            loaded = load_register(path)
            self.assertEqual(loaded["directions"]["AI算力"]["current_status"], "elevated")


class EscalationTests(unittest.TestCase):
    def test_normal_to_elevated_on_first_caution(self) -> None:
        reg = empty_register()
        reg = update_register(reg, _postclose("AI", status="caution"), "2025-09-29")
        self.assertEqual(direction_risk_level(reg, "AI"), "elevated")

    def test_normal_to_elevated_on_overheat_alone(self) -> None:
        reg = empty_register()
        reg = update_register(
            reg, _postclose("AI", status="confirmed", overheat=True), "2025-09-29"
        )
        self.assertEqual(direction_risk_level(reg, "AI"), "elevated")

    def test_elevated_to_restricted_after_two_caution_days(self) -> None:
        reg = empty_register()
        reg = update_register(reg, _postclose("AI", status="caution"), "2025-09-29")
        self.assertEqual(direction_risk_level(reg, "AI"), "elevated")
        reg = update_register(reg, _postclose("AI", status="caution"), "2025-09-30")
        self.assertEqual(direction_risk_level(reg, "AI"), "restricted")
        entry = reg["directions"]["AI"]
        self.assertEqual(entry["consecutive_caution_days"], 2)
        self.assertTrue(entry["restriction_reason"])
        self.assertTrue(entry["restriction_expires"])

    def test_elevated_to_restricted_on_overheat_plus_divergence(self) -> None:
        reg = empty_register()
        # Day 1: caution to land in elevated.
        reg = update_register(reg, _postclose("AI", status="caution"), "2025-09-28")
        self.assertEqual(direction_risk_level(reg, "AI"), "elevated")
        # Day 2: confirmed but with overheat + divergence on the same day.
        reg = update_register(
            reg,
            _postclose("AI", status="confirmed", overheat=True, divergence=True),
            "2025-09-29",
        )
        self.assertEqual(direction_risk_level(reg, "AI"), "restricted")


class DeEscalationTests(unittest.TestCase):
    def _restrict(self) -> dict:
        reg = empty_register()
        reg = update_register(reg, _postclose("AI", status="caution"), "2025-09-29")
        reg = update_register(reg, _postclose("AI", status="caution"), "2025-09-30")
        self.assertEqual(direction_risk_level(reg, "AI"), "restricted")
        return reg

    def test_restricted_to_elevated_on_one_good_day(self) -> None:
        reg = self._restrict()
        reg = update_register(reg, _postclose("AI", status="confirmed"), "2025-10-01")
        self.assertEqual(direction_risk_level(reg, "AI"), "elevated")
        entry = reg["directions"]["AI"]
        self.assertEqual(entry["restriction_reason"], "")
        self.assertEqual(entry["restriction_expires"], "")

    def test_elevated_to_normal_after_two_good_days(self) -> None:
        reg = self._restrict()
        reg = update_register(reg, _postclose("AI", status="confirmed"), "2025-10-01")
        self.assertEqual(direction_risk_level(reg, "AI"), "elevated")
        reg = update_register(reg, _postclose("AI", status="strengthening"), "2025-10-02")
        # Still elevated after one day of good momentum following restriction lift.
        self.assertEqual(direction_risk_level(reg, "AI"), "elevated")
        reg = update_register(reg, _postclose("AI", status="confirmed"), "2025-10-03")
        self.assertEqual(direction_risk_level(reg, "AI"), "normal")

    def test_good_day_with_overheat_does_not_count(self) -> None:
        reg = empty_register()
        reg = update_register(
            reg, _postclose("AI", status="confirmed", overheat=True), "2025-09-29"
        )
        self.assertEqual(direction_risk_level(reg, "AI"), "elevated")
        # Two more good days but each carrying overheat: should stay elevated.
        reg = update_register(
            reg, _postclose("AI", status="confirmed", overheat=True), "2025-09-30"
        )
        reg = update_register(
            reg, _postclose("AI", status="confirmed", overheat=True), "2025-10-01"
        )
        self.assertEqual(direction_risk_level(reg, "AI"), "elevated")


class AutoExpiryTests(unittest.TestCase):
    def test_restriction_expires_after_default_window(self) -> None:
        reg = empty_register()
        reg = update_register(reg, _postclose("AI", status="caution"), "2025-09-29")
        reg = update_register(reg, _postclose("AI", status="caution"), "2025-09-30")
        self.assertEqual(direction_risk_level(reg, "AI"), "restricted")
        expiry = reg["directions"]["AI"]["restriction_expires"]
        # Run an update on or after the expiry date with no signals for AI.
        reg = update_register(reg, {"direction_momentum": []}, expiry)
        self.assertEqual(direction_risk_level(reg, "AI"), "elevated")

    def test_configurable_restriction_window(self) -> None:
        reg = empty_register()
        reg = update_register(
            reg, _postclose("AI", status="caution"), "2025-09-29",
            restriction_days=2,
        )
        reg = update_register(
            reg, _postclose("AI", status="caution"), "2025-09-30",
            restriction_days=2,
        )
        self.assertEqual(reg["directions"]["AI"]["restriction_expires"], "2025-10-02")
        self.assertNotEqual(DEFAULT_RESTRICTION_DAYS, 2)


class HistoryTests(unittest.TestCase):
    def test_history_truncates_at_limit(self) -> None:
        reg = empty_register()
        # Push 25 entries, alternating caution/confirmed to keep the state stable enough.
        for i in range(25):
            d = f"2025-09-{(i % 28) + 1:02d}"
            status = "confirmed" if i % 2 == 0 else "caution"
            reg = update_register(reg, _postclose("AI", status=status), d)
        history = reg["directions"]["AI"]["history"]
        self.assertEqual(len(history), HISTORY_LIMIT)
        # Last entry is i=24 (even) → "confirmed"; first kept entry is i=5 (odd) → "caution".
        self.assertEqual(history[-1]["momentum_status"], "confirmed")
        self.assertEqual(history[0]["momentum_status"], "caution")


class IntegrationHookTests(unittest.TestCase):
    def test_apply_attaches_summary_and_warnings(self) -> None:
        reg = empty_register()
        reg = update_register(reg, _postclose("AI", status="caution"), "2025-09-29")
        reg = update_register(reg, _postclose("AI", status="caution"), "2025-09-30")
        package = {
            "trade_cards": [
                {"ticker": "300750.SZ", "direction_key": "AI", "trade_card": {"watch_action": "buy"}},
                {"ticker": "600519.SS", "direction_key": "Liquor", "trade_card": {"watch_action": "hold"}},
            ],
        }
        apply_direction_risk_to_package(package, reg)
        self.assertIn("direction_risk_register_summary", package)
        ai_card = package["trade_cards"][0]["trade_card"]
        self.assertIn("direction_risk_warning", ai_card)
        self.assertEqual(ai_card["direction_risk_warning"]["risk_level"], "restricted")
        liquor_card = package["trade_cards"][1]["trade_card"]
        self.assertNotIn("direction_risk_warning", liquor_card)

    def test_apply_handles_direction_boost_shape(self) -> None:
        reg = empty_register()
        reg = update_register(
            reg, _postclose("AI", status="confirmed", overheat=True), "2025-09-29"
        )
        package = {
            "longbridge_candidates": [
                {
                    "ticker": "300750.SZ",
                    "direction_boost": {"direction_key": "AI"},
                    "trade_card": {"watch_action": "buy"},
                },
            ],
        }
        apply_direction_risk_to_package(package, reg)
        warning = package["longbridge_candidates"][0]["trade_card"]["direction_risk_warning"]
        self.assertEqual(warning["risk_level"], "elevated")


class QueryTests(unittest.TestCase):
    def test_restricted_and_elevated_lists(self) -> None:
        reg = empty_register()
        reg = update_register(reg, _postclose("AI", status="caution"), "2025-09-29")
        reg = update_register(reg, _postclose("AI", status="caution"), "2025-09-30")
        reg = update_register(reg, _postclose("Liquor", status="caution"), "2025-09-30")
        self.assertEqual(restricted_directions(reg), ["AI"])
        self.assertEqual(elevated_directions(reg), ["Liquor"])

    def test_risk_summary_counts(self) -> None:
        reg = empty_register()
        reg = update_register(reg, _postclose("AI", status="caution"), "2025-09-29")
        reg = update_register(reg, _postclose("AI", status="caution"), "2025-09-30")
        reg = update_register(reg, _postclose("Liquor", status="caution"), "2025-09-30")
        summary = risk_summary(reg)
        self.assertEqual(summary["counts"]["restricted"], 1)
        self.assertEqual(summary["counts"]["elevated"], 1)
        self.assertEqual(summary["most_restricted_direction"], "AI")


class MarkdownTests(unittest.TestCase):
    def test_renders_table(self) -> None:
        reg = empty_register()
        reg = update_register(reg, _postclose("AI", status="caution"), "2025-09-30")
        md = render_risk_register_markdown(reg)
        self.assertIn("方向风险登记表", md)
        self.assertIn("AI", md)
        self.assertIn("elevated", md)


if __name__ == "__main__":
    unittest.main()
