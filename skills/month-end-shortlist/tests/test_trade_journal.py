#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from trade_journal_runtime import (  # noqa: E402
    DEFAULT_JOURNAL_NAME,
    compute_stats,
    default_journal_path,
    load_journal,
    open_positions,
    record_decision,
    record_decisions_from_package,
    record_outcome,
    record_outcomes_from_postclose,
)


@contextmanager
def _tempdir():
    with tempfile.TemporaryDirectory() as raw:
        yield Path(raw)


def _today_iso() -> str:
    return date.today().isoformat()


def _days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


class AppendAndLoadTests(unittest.TestCase):
    def test_default_journal_path_uses_output_root(self) -> None:
        with _tempdir() as tmp:
            self.assertEqual(default_journal_path(tmp), tmp / DEFAULT_JOURNAL_NAME)

    def test_round_trip_decision_and_outcome(self) -> None:
        with _tempdir() as tmp:
            path = tmp / "journal.jsonl"
            decision = record_decision(
                path,
                decision_date="2025-09-30",
                ticker="AAPL.US",
                name="Apple",
                market="us",
                action="buy_trigger",
                source_layer="x_seed",
                trigger_price=170.5,
                stop_loss=160.0,
                abandon_below=155.0,
                entry_price=171.0,
                decision_context="breakout above 170 with volume",
            )
            outcome = record_outcome(
                path,
                journal_id=decision["journal_id"],
                outcome_type="t1",
                outcome_date="2025-10-01",
                close_price=174.0,
                return_pct=1.75,
                outcome_label="still_holding",
            )

            entries = load_journal(path)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["entry_kind"], "decision")
            self.assertEqual(entries[0]["ticker"], "AAPL.US")
            self.assertEqual(entries[0]["trigger_price"], 170.5)
            self.assertEqual(entries[0]["entry_price"], 171.0)
            self.assertEqual(entries[1]["entry_kind"], "outcome")
            self.assertEqual(entries[1]["journal_id"], decision["journal_id"])
            self.assertEqual(entries[1]["return_pct"], 1.75)
            self.assertEqual(outcome["outcome_label"], "still_holding")

    def test_load_missing_file_returns_empty_list(self) -> None:
        with _tempdir() as tmp:
            self.assertEqual(load_journal(tmp / "missing.jsonl"), [])

    def test_corrupt_lines_are_skipped(self) -> None:
        with _tempdir() as tmp:
            path = tmp / "journal.jsonl"
            path.write_text(
                "{not json}\n"
                + '{"entry_kind":"decision","journal_id":"abc","ticker":"AAA"}\n'
                + "\n",
                encoding="utf-8",
            )
            entries = load_journal(path)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["journal_id"], "abc")


class DuplicateDetectionTests(unittest.TestCase):
    def test_record_decisions_skips_existing_ticker_date(self) -> None:
        with _tempdir() as tmp:
            path = tmp / "journal.jsonl"
            package = {
                "month_end_request": {"target_date": "2025-09-30"},
                "local_stock_pool": {
                    "stocks": [
                        {
                            "ticker": "AAPL.US",
                            "name": "Apple",
                            "plan_snapshot": {
                                "trade_card": {
                                    "watch_action": "突破后试仓",
                                    "invalidation": "跌破止损",
                                },
                                "price_paths": {
                                    "base": [170.0],
                                    "resistance": [180.0],
                                    "support": [160.0, 155.0],
                                },
                            },
                            "source_layer": "x_seed",
                        },
                        {
                            "ticker": "600519.SH",
                            "name": "Kweichow Moutai",
                            "plan_snapshot": {
                                "trade_card": {"watch_action": "保持观察"},
                            },
                            "source": "weekend_candidate",
                        },
                    ]
                },
            }

            first = record_decisions_from_package(package, path)
            second = record_decisions_from_package(package, path)

            self.assertEqual(len(first), 2)
            self.assertEqual(second, [])

            entries = load_journal(path)
            decisions = [e for e in entries if e["entry_kind"] == "decision"]
            self.assertEqual(len(decisions), 2)

            apple = next(e for e in decisions if e["ticker"] == "AAPL.US")
            self.assertEqual(apple["market"], "us")
            self.assertEqual(apple["action"], "buy_trigger")
            self.assertEqual(apple["source_layer"], "x_seed")
            self.assertEqual(apple["trigger_price"], 180.0)
            self.assertEqual(apple["stop_loss"], 160.0)
            self.assertEqual(apple["abandon_below"], 155.0)

            moutai = next(e for e in decisions if e["ticker"] == "600519.SH")
            self.assertEqual(moutai["market"], "a_share")
            self.assertEqual(moutai["action"], "watch")
            self.assertEqual(moutai["source_layer"], "weekend_candidate")


class OpenPositionsTests(unittest.TestCase):
    def test_filters_by_action_entry_price_and_terminal_outcome(self) -> None:
        with _tempdir() as tmp:
            path = tmp / "journal.jsonl"

            triggered = record_decision(
                path,
                decision_date="2025-09-01",
                ticker="AAA",
                name="AAA",
                market="us",
                action="buy_trigger",
                source_layer="x_seed",
                entry_price=10.0,
            )
            record_decision(
                path,
                decision_date="2025-09-01",
                ticker="BBB",
                name="BBB",
                market="us",
                action="buy_trigger",
                source_layer="x_seed",
                entry_price=None,
            )
            record_decision(
                path,
                decision_date="2025-09-01",
                ticker="CCC",
                name="CCC",
                market="us",
                action="watch",
                source_layer="x_seed",
                entry_price=20.0,
            )
            stopped = record_decision(
                path,
                decision_date="2025-09-01",
                ticker="DDD",
                name="DDD",
                market="us",
                action="buy_trigger",
                source_layer="x_seed",
                entry_price=30.0,
            )
            record_outcome(
                path,
                journal_id=stopped["journal_id"],
                outcome_type="exit",
                outcome_date="2025-09-05",
                return_pct=-4.0,
                outcome_label="stopped_out",
            )
            # add a non-terminal outcome on the still-open one
            record_outcome(
                path,
                journal_id=triggered["journal_id"],
                outcome_type="t1",
                outcome_date="2025-09-02",
                return_pct=1.0,
                outcome_label="still_holding",
            )

            journal = load_journal(path)
            opens = open_positions(journal)
            self.assertEqual([d["ticker"] for d in opens], ["AAA"])


class StatsComputationTests(unittest.TestCase):
    def test_stats_with_known_data(self) -> None:
        with _tempdir() as tmp:
            path = tmp / "journal.jsonl"

            wins = [
                ("WIN1", "x_seed", 6.0, "target_reached"),
                ("WIN2", "x_seed", 4.0, "target_reached"),
                ("WIN3", "reddit", 8.0, "target_reached"),
            ]
            losses = [
                ("LOSE1", "x_seed", -3.0, "stopped_out"),
                ("LOSE2", "reddit", -5.0, "stopped_out"),
            ]
            for ticker, layer, ret, label in wins + losses:
                d = record_decision(
                    path,
                    decision_date=_days_ago(10),
                    ticker=ticker,
                    name=ticker,
                    market="us",
                    action="buy_trigger",
                    source_layer=layer,
                    entry_price=100.0,
                )
                record_outcome(
                    path,
                    journal_id=d["journal_id"],
                    outcome_type="exit",
                    outcome_date=_days_ago(5),
                    return_pct=ret,
                    outcome_label=label,
                )

            # outside lookback window — should be excluded
            old = record_decision(
                path,
                decision_date=_days_ago(200),
                ticker="OLD",
                name="OLD",
                market="us",
                action="buy_trigger",
                source_layer="x_seed",
                entry_price=100.0,
            )
            record_outcome(
                path,
                journal_id=old["journal_id"],
                outcome_type="exit",
                outcome_date=_days_ago(195),
                return_pct=20.0,
                outcome_label="target_reached",
            )

            # non buy_trigger — excluded from stats
            record_decision(
                path,
                decision_date=_days_ago(5),
                ticker="WATCH1",
                name="WATCH1",
                market="us",
                action="watch",
                source_layer="x_seed",
            )

            journal = load_journal(path)
            stats = compute_stats(journal, lookback_days=90)

            self.assertEqual(stats["count"], 5)
            self.assertEqual(stats["resolved"], 5)
            self.assertEqual(stats["wins"], 3)
            self.assertEqual(stats["losses"], 2)
            self.assertAlmostEqual(stats["hit_rate"], 0.6, places=4)
            # avg_win = 6, avg_loss = -4; expectancy = 0.6*6 + 0.4*-4 = 2.0
            self.assertAlmostEqual(stats["expectancy"], 2.0, places=4)
            self.assertAlmostEqual(stats["avg_return"], 2.0, places=4)
            self.assertAlmostEqual(stats["max_drawdown_pct"], -5.0, places=4)

            by_layer = stats["by_source_layer"]
            self.assertIn("x_seed", by_layer)
            self.assertIn("reddit", by_layer)
            self.assertEqual(by_layer["x_seed"]["count"], 3)
            self.assertEqual(by_layer["reddit"]["count"], 2)
            self.assertAlmostEqual(by_layer["reddit"]["hit_rate"], 0.5, places=4)

    def test_stats_empty_journal(self) -> None:
        stats = compute_stats([], lookback_days=90)
        self.assertEqual(stats["count"], 0)
        self.assertEqual(stats["resolved"], 0)
        self.assertEqual(stats["hit_rate"], 0.0)
        self.assertEqual(stats["expectancy"], 0.0)
        self.assertEqual(stats["max_drawdown_pct"], 0.0)
        self.assertEqual(stats["by_source_layer"], {})


class PostcloseIntegrationTests(unittest.TestCase):
    def test_outcomes_link_to_open_decisions(self) -> None:
        with _tempdir() as tmp:
            path = tmp / "journal.jsonl"
            decision = record_decision(
                path,
                decision_date="2025-09-30",
                ticker="600519.SS",
                name="Kweichow Moutai",
                market="a_share",
                action="buy_trigger",
                source_layer="weekend_candidate",
                entry_price=1700.0,
            )
            # one watch-only decision should not receive an outcome
            record_decision(
                path,
                decision_date="2025-09-30",
                ticker="000001.SZ",
                name="Ping An Bank",
                market="a_share",
                action="watch",
                source_layer="x_seed",
            )

            postclose = {
                "trade_date": "2025-10-08",
                "candidates_reviewed": [
                    {
                        "ticker": "600519.SH",  # different suffix style
                        "name": "Kweichow Moutai",
                        "plan_action": "可执行",
                        "actual_return_pct": 6.5,
                        "judgment": "plan_correct",
                        "close": 1810.5,
                    },
                    {
                        "ticker": "999999.SS",  # not in journal
                        "name": "Unknown",
                        "plan_action": "可执行",
                        "actual_return_pct": 1.0,
                        "judgment": "plan_correct",
                        "close": 50.0,
                    },
                    {
                        "ticker": "000001.SZ",  # only watch — no entry_price
                        "name": "Ping An Bank",
                        "plan_action": "继续观察",
                        "actual_return_pct": -0.5,
                        "judgment": "plan_correct_negative",
                        "close": 12.0,
                    },
                ],
            }

            appended = record_outcomes_from_postclose(postclose, path)
            self.assertEqual(len(appended), 1)
            self.assertEqual(appended[0]["journal_id"], decision["journal_id"])
            self.assertEqual(appended[0]["outcome_type"], "t1")
            self.assertEqual(appended[0]["outcome_label"], "target_reached")
            self.assertEqual(appended[0]["return_pct"], 6.5)
            self.assertEqual(appended[0]["close_price"], 1810.5)

            # second invocation should be idempotent
            second = record_outcomes_from_postclose(postclose, path)
            self.assertEqual(second, [])

            journal = load_journal(path)
            outcomes = [e for e in journal if e["entry_kind"] == "outcome"]
            self.assertEqual(len(outcomes), 1)


if __name__ == "__main__":
    unittest.main()
