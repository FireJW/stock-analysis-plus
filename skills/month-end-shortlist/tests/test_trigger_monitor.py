#!/usr/bin/env python3
"""Tests for trigger_monitor_runtime."""
from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import trigger_monitor_runtime as tm  # noqa: E402


def _card(
    ticker: str,
    *,
    trigger: float | None = None,
    stop: float | None = None,
    abandon: float | None = None,
    name: str | None = None,
) -> dict:
    return {
        "ticker": ticker,
        "longbridge_ticker": tm.to_longbridge_ticker(ticker),
        "name": name or ticker,
        "trigger_price": trigger,
        "stop_loss": stop,
        "abandon_below": abandon,
        "watch_action": "",
        "invalidation": "",
    }


class TickerNormalizationTests(unittest.TestCase):
    def test_ss_suffix_converted_to_sh(self) -> None:
        self.assertEqual(tm.to_longbridge_ticker("600519.SS"), "600519.SH")

    def test_sz_passthrough(self) -> None:
        self.assertEqual(tm.to_longbridge_ticker("000001.SZ"), "000001.SZ")

    def test_us_passthrough(self) -> None:
        self.assertEqual(tm.to_longbridge_ticker("AAPL.US"), "AAPL.US")

    def test_empty_input(self) -> None:
        self.assertEqual(tm.to_longbridge_ticker(""), "")
        self.assertEqual(tm.to_longbridge_ticker(None), "")


class AlertDetectionTests(unittest.TestCase):
    def test_trigger_hit_emits_alert(self) -> None:
        cards = [_card("600519.SS", trigger=100.0, stop=80.0)]
        quotes = {"600519.SH": {"last_done": 101.0, "timestamp": "2026-05-17T10:00:00Z"}}
        alerts = tm.detect_trigger_alerts(cards, quotes)
        types_seen = {a["alert_type"] for a in alerts}
        self.assertIn("trigger_hit", types_seen)
        self.assertNotIn("stop_hit", types_seen)
        self.assertNotIn("trigger_approaching", types_seen)
        hit = next(a for a in alerts if a["alert_type"] == "trigger_hit")
        self.assertEqual(hit["ticker"], "600519.SS")
        self.assertEqual(hit["level_price"], 100.0)
        self.assertEqual(hit["last_done"], 101.0)

    def test_stop_hit_emits_alert(self) -> None:
        cards = [_card("000001.SZ", trigger=20.0, stop=10.0)]
        quotes = {"000001.SZ": {"last_done": 9.5}}
        alerts = tm.detect_trigger_alerts(cards, quotes)
        types_seen = {a["alert_type"] for a in alerts}
        self.assertIn("stop_hit", types_seen)
        self.assertNotIn("stop_approaching", types_seen)

    def test_abandon_hit_alert(self) -> None:
        cards = [_card("000001.SZ", stop=10.0, abandon=8.0)]
        quotes = {"000001.SZ": {"last_done": 7.5}}
        alerts = tm.detect_trigger_alerts(cards, quotes)
        types_seen = {a["alert_type"] for a in alerts}
        self.assertIn("abandon_hit", types_seen)
        self.assertIn("stop_hit", types_seen)

    def test_trigger_approaching_within_two_pct(self) -> None:
        cards = [_card("600519.SS", trigger=100.0, stop=80.0)]
        quotes = {"600519.SH": {"last_done": 99.0}}
        alerts = tm.detect_trigger_alerts(cards, quotes)
        types_seen = {a["alert_type"] for a in alerts}
        self.assertIn("trigger_approaching", types_seen)
        self.assertNotIn("trigger_hit", types_seen)

    def test_stop_approaching_within_two_pct(self) -> None:
        cards = [_card("600519.SS", trigger=100.0, stop=80.0)]
        quotes = {"600519.SH": {"last_done": 81.0}}
        alerts = tm.detect_trigger_alerts(cards, quotes)
        types_seen = {a["alert_type"] for a in alerts}
        self.assertIn("stop_approaching", types_seen)
        self.assertNotIn("stop_hit", types_seen)

    def test_no_alert_when_far_from_levels(self) -> None:
        cards = [_card("600519.SS", trigger=100.0, stop=80.0)]
        quotes = {"600519.SH": {"last_done": 90.0}}
        alerts = tm.detect_trigger_alerts(cards, quotes)
        self.assertEqual(alerts, [])

    def test_missing_last_done_skipped(self) -> None:
        cards = [_card("600519.SS", trigger=100.0)]
        quotes = {"600519.SH": {"last_done": None}}
        self.assertEqual(tm.detect_trigger_alerts(cards, quotes), [])

    def test_none_levels_dont_emit(self) -> None:
        cards = [_card("600519.SS", trigger=None, stop=None, abandon=None)]
        quotes = {"600519.SH": {"last_done": 100.0}}
        self.assertEqual(tm.detect_trigger_alerts(cards, quotes), [])

    def test_quote_missing_for_card(self) -> None:
        cards = [_card("600519.SS", trigger=100.0, stop=80.0)]
        self.assertEqual(tm.detect_trigger_alerts(cards, {}), [])

    def test_ss_quote_format_still_matches(self) -> None:
        cards = [_card("600519.SS", trigger=100.0)]
        # quote came back keyed by .SS rather than .SH
        quotes = {"600519.SS": {"last_done": 101.0}}
        alerts = tm.detect_trigger_alerts(cards, quotes)
        self.assertEqual(len(alerts), 1)


class ExtractActiveTradeCardsTests(unittest.TestCase):
    def test_extracts_cards_with_levels_from_trade_card(self) -> None:
        package = {
            "local_stock_pool": {
                "stocks": [
                    {
                        "ticker": "600519.SS",
                        "name": "Moutai",
                        "trade_card": {
                            "trigger_price": 1800.0,
                            "stop_loss": 1600.0,
                            "abandon_below": 1500.0,
                            "watch_action": "wait for breakout",
                        },
                    },
                ]
            }
        }
        cards = tm.extract_active_trade_cards(package)
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card["ticker"], "600519.SS")
        self.assertEqual(card["longbridge_ticker"], "600519.SH")
        self.assertEqual(card["trigger_price"], 1800.0)
        self.assertEqual(card["stop_loss"], 1600.0)
        self.assertEqual(card["abandon_below"], 1500.0)
        self.assertEqual(card["watch_action"], "wait for breakout")

    def test_extracts_levels_from_plan_snapshot_price_paths(self) -> None:
        package = {
            "local_stock_pool": {
                "stocks": [
                    {
                        "ticker": "000001.SZ",
                        "name": "PAB",
                        "plan_snapshot": {
                            "price_paths": {
                                "resistance": [12.5],
                                "support": [10.0, 9.0],
                            },
                            "trade_card": {"watch_action": "observe"},
                        },
                    },
                ]
            }
        }
        cards = tm.extract_active_trade_cards(package)
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card["trigger_price"], 12.5)
        self.assertEqual(card["stop_loss"], 10.0)
        self.assertEqual(card["watch_action"], "observe")

    def test_skips_cards_without_levels(self) -> None:
        package = {
            "local_stock_pool": {
                "stocks": [
                    {"ticker": "600519.SS", "name": "no levels"},
                    {"ticker": "000001.SZ", "trade_card": {"trigger_price": 12.0}},
                ]
            }
        }
        cards = tm.extract_active_trade_cards(package)
        self.assertEqual([c["ticker"] for c in cards], ["000001.SZ"])

    def test_empty_pool_returns_empty(self) -> None:
        self.assertEqual(tm.extract_active_trade_cards({}), [])
        self.assertEqual(tm.extract_active_trade_cards({"local_stock_pool": {}}), [])
        self.assertEqual(
            tm.extract_active_trade_cards({"local_stock_pool": {"stocks": []}}),
            [],
        )

    def test_invalid_stock_entries_ignored(self) -> None:
        package = {
            "local_stock_pool": {
                "stocks": [None, "string", {"ticker": "", "trade_card": {"trigger_price": 1}}],
            }
        }
        self.assertEqual(tm.extract_active_trade_cards(package), [])


class FetchQuotesTests(unittest.TestCase):
    def test_parses_list_payload(self) -> None:
        completed = types.SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "symbol": "600519.SH",
                        "last_done": "1801.5",
                        "prev_close": "1780.0",
                        "high": "1810.0",
                        "low": "1770.0",
                        "volume": "1234567",
                        "timestamp": "2026-05-17T01:30:00Z",
                    }
                ]
            ),
            stderr="",
        )

        def runner(cmd, timeout):
            self.assertEqual(cmd[0], "longbridge")
            self.assertEqual(cmd[1], "quote")
            self.assertEqual(cmd[2], "600519.SH")
            self.assertIn("--format", cmd)
            return completed

        quotes = tm.fetch_quotes(["600519.SH"], runner=runner)
        self.assertIn("600519.SH", quotes)
        quote = quotes["600519.SH"]
        self.assertEqual(quote["last_done"], 1801.5)
        self.assertEqual(quote["prev_close"], 1780.0)
        self.assertEqual(quote["high"], 1810.0)
        self.assertEqual(quote["low"], 1770.0)
        self.assertEqual(quote["volume"], 1234567.0)
        self.assertEqual(quote["timestamp"], "2026-05-17T01:30:00Z")

    def test_multiple_tickers_are_sent_as_separate_cli_args(self) -> None:
        completed = types.SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {"symbol": "600519.SH", "last_done": "1801.5"},
                    {"symbol": "000001.SZ", "last_done": "12.3"},
                ]
            ),
            stderr="",
        )

        def runner(cmd, timeout):
            self.assertEqual(cmd[:4], ["longbridge", "quote", "600519.SH", "000001.SZ"])
            self.assertIn("--format", cmd)
            return completed

        quotes = tm.fetch_quotes(["600519.SH", "000001.SZ"], runner=runner)
        self.assertEqual(quotes["600519.SH"]["last_done"], 1801.5)
        self.assertEqual(quotes["000001.SZ"]["last_done"], 12.3)

    def test_parses_wrapped_dict_payload(self) -> None:
        completed = types.SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "data": [
                        {"symbol": "AAPL.US", "last": 195.55, "prev_close": 192.0},
                    ]
                }
            ),
            stderr="",
        )
        quotes = tm.fetch_quotes(["AAPL.US"], runner=lambda cmd, timeout: completed)
        self.assertEqual(quotes["AAPL.US"]["last_done"], 195.55)

    def test_returns_empty_on_nonzero_exit(self) -> None:
        completed = types.SimpleNamespace(returncode=1, stdout="", stderr="boom")
        self.assertEqual(tm.fetch_quotes(["X.US"], runner=lambda c, timeout: completed), {})

    def test_returns_empty_on_bad_json(self) -> None:
        completed = types.SimpleNamespace(returncode=0, stdout="not json", stderr="")
        self.assertEqual(tm.fetch_quotes(["X.US"], runner=lambda c, timeout: completed), {})

    def test_returns_empty_when_runner_raises(self) -> None:
        def boom(cmd, timeout):
            raise RuntimeError("subprocess died")

        self.assertEqual(tm.fetch_quotes(["X.US"], runner=boom), {})

    def test_no_tickers_short_circuits(self) -> None:
        # runner should never run if there is nothing to quote
        called = {"count": 0}

        def runner(cmd, timeout):
            called["count"] += 1
            return types.SimpleNamespace(returncode=0, stdout="[]", stderr="")

        self.assertEqual(tm.fetch_quotes([], runner=runner), {})
        self.assertEqual(called["count"], 0)


class RunMonitorCycleTests(unittest.TestCase):
    def test_full_cycle_with_injected_fetcher(self) -> None:
        package = {
            "local_stock_pool": {
                "stocks": [
                    {
                        "ticker": "600519.SS",
                        "name": "Moutai",
                        "trade_card": {"trigger_price": 1800.0, "stop_loss": 1600.0},
                    },
                    {
                        "ticker": "000001.SZ",
                        "name": "PAB",
                        "trade_card": {"trigger_price": 15.0, "stop_loss": 10.0},
                    },
                ]
            }
        }
        tmp_path = Path.cwd() / ".tmp" / "trigger-monitor-cycle.json"
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")

        captured: dict[str, list[str]] = {}

        def fetcher(tickers):
            captured["tickers"] = list(tickers)
            return {
                "600519.SH": {"last_done": 1810.0},
                "000001.SZ": {"last_done": 11.0},
            }

        try:
            result = tm.run_monitor_cycle(tmp_path, quote_fetcher=fetcher)
        finally:
            tmp_path.unlink(missing_ok=True)

        self.assertEqual(result["schema_version"], "trigger_monitor/v1")
        self.assertEqual(result["active_cards_count"], 2)
        self.assertEqual(result["quotes_fetched"], 2)
        self.assertIn("600519.SH", captured["tickers"])
        self.assertIn("000001.SZ", captured["tickers"])
        types_seen = {a["alert_type"] for a in result["alerts"]}
        self.assertIn("trigger_hit", types_seen)


class FormatAlertsMarkdownTests(unittest.TestCase):
    def test_empty_alerts_returns_placeholder(self) -> None:
        self.assertIn("No active", tm.format_alerts_markdown([]))

    def test_renders_table(self) -> None:
        rendered = tm.format_alerts_markdown(
            [
                {
                    "ticker": "600519.SS",
                    "name": "Moutai",
                    "alert_type": "trigger_hit",
                    "level_name": "trigger_price",
                    "level_price": 1800.0,
                    "last_done": 1810.0,
                    "distance_pct": 0.555,
                    "timestamp": "2026-05-17T01:30:00Z",
                }
            ]
        )
        self.assertIn("trigger_hit", rendered)
        self.assertIn("600519.SS", rendered)
        self.assertIn("1800.000", rendered)
        self.assertIn("1810.000", rendered)


class MainCliTests(unittest.TestCase):
    def test_main_writes_output_and_exits_zero(self) -> None:
        package = {
            "local_stock_pool": {
                "stocks": [
                    {
                        "ticker": "600519.SS",
                        "name": "Moutai",
                        "trade_card": {"trigger_price": 1800.0, "stop_loss": 1600.0},
                    }
                ]
            }
        }
        tmp_dir = Path.cwd() / ".tmp" / "trigger-monitor-cli"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        package_path = tmp_dir / "package.json"
        output_path = tmp_dir / "alerts.json"
        package_path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")

        def fake_run_cycle(path, binary, **kwargs):
            return {
                "schema_version": "trigger_monitor/v1",
                "cycle_time": "2026-05-17T01:30:00+00:00",
                "active_cards_count": 1,
                "quotes_fetched": 1,
                "alerts": [
                    {
                        "ticker": "600519.SS",
                        "name": "Moutai",
                        "alert_type": "trigger_hit",
                        "level_name": "trigger_price",
                        "level_price": 1800.0,
                        "last_done": 1810.0,
                        "distance_pct": 0.5,
                        "timestamp": "2026-05-17T01:30:00Z",
                    }
                ],
            }

        try:
            with mock.patch.object(tm, "run_monitor_cycle", side_effect=fake_run_cycle):
                rc = tm.main(
                    [
                        "--package-path",
                        str(package_path),
                        "--output",
                        str(output_path),
                        "--quiet",
                    ]
                )
            self.assertEqual(rc, 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["alerts"][0]["alert_type"], "trigger_hit")
        finally:
            package_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
            tmp_dir.rmdir()

    def test_main_returns_two_when_package_missing(self) -> None:
        rc = tm.main(["--package-path", "Z:/nope/never.json", "--quiet"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
