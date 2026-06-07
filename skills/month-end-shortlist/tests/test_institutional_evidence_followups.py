#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from local_stock_pool_manager_runtime import (  # noqa: E402
    build_ownership_fundamental_argv,
    refresh_institutional_evidence_followup_result_state,
    write_institutional_evidence_followup_requests,
    write_local_stock_pool_manager_package,
)


def _base_package(target_date: str = "2025-09-30") -> dict:
    return {
        "month_end_request": {"target_date": target_date, "analysis_time": target_date},
        "local_stock_pool": {
            "stocks": [
                {
                    "ticker": "AAPL.US",
                    "name": "Apple",
                    "plan_snapshot": {"chain_name": "Consumer Electronics"},
                },
                {
                    "ticker": "600519.SH",
                    "name": "Kweichow Moutai",
                    "plan_snapshot": {"chain_name": "Liquor"},
                },
            ]
        },
        "institutional_signal_audit": {
            "upgrade_priorities": [
                {"id": "social_altdata"},
                {"id": "ownership_fundamental"},
            ]
        },
    }


class WriteFollowupRequestsTests(unittest.TestCase):
    def test_stub_only_mode_writes_request_files_without_running(self) -> None:
        with _tempdir() as tmp:
            package = _base_package()
            x_calls: list[dict] = []
            bundle_calls: list[list[str]] = []

            def x_runner(payload: dict) -> dict:
                x_calls.append(payload)
                return {}

            def bundle_runner(argv: list[str]) -> int:
                bundle_calls.append(argv)
                return 0

            followups = write_institutional_evidence_followup_requests(
                package,
                shortlist_result=None,
                output_root=tmp,
                execute=False,
                x_index_runner=x_runner,
                evidence_bundle_runner=bundle_runner,
            )

            self.assertEqual([row["id"] for row in followups], ["social_altdata", "ownership_fundamental"])
            for row in followups:
                self.assertEqual(row["status"], "request_ready")
                self.assertNotIn("execution_mode", row)
                self.assertTrue(Path(row["request_path"]).exists())
            self.assertEqual(x_calls, [])
            self.assertEqual(bundle_calls, [])

    def test_execute_mode_invokes_runners_and_marks_status(self) -> None:
        with _tempdir() as tmp:
            package = _base_package()
            x_calls: list[dict] = []
            bundle_calls: list[list[str]] = []

            def x_runner(payload: dict) -> dict:
                x_calls.append(payload)
                output_dir = Path(payload["output_dir"])
                output_dir.mkdir(parents=True, exist_ok=True)
                result = {
                    "schema_version": "x-index/v1",
                    "x_posts": [
                        {"author_handle": "alice", "post_url": "https://x.com/alice/1"},
                        {"author_handle": "bob", "post_url": "https://x.com/bob/2"},
                    ],
                }
                (output_dir / "x-index-result.json").write_text(
                    json.dumps(result, ensure_ascii=False), encoding="utf-8"
                )
                (output_dir / "x-index-report.md").write_text("# x-index report\n", encoding="utf-8")
                return result

            def bundle_runner(argv: list[str]) -> int:
                bundle_calls.append(argv)
                output_index = argv.index("--output")
                output_path = Path(argv[output_index + 1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                bundle = {
                    "schema_version": "institutional-evidence-bundle/v1",
                    "summary": {"filing_count": 2, "fundamental_report_count": 1, "ownership_record_count": 0},
                    "filings": [{"ticker": "AAPL", "form": "10-Q"}, {"ticker": "AAPL", "form": "8-K"}],
                    "fundamentals": {"reports": [{"ticker": "600519"}]},
                }
                output_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
                md_index = argv.index("--markdown-output")
                Path(argv[md_index + 1]).write_text("# bundle\n", encoding="utf-8")
                return 0

            followups = write_institutional_evidence_followup_requests(
                package,
                shortlist_result=None,
                output_root=tmp,
                execute=True,
                x_index_runner=x_runner,
                evidence_bundle_runner=bundle_runner,
            )

            social = _by_id(followups, "social_altdata")
            ownership = _by_id(followups, "ownership_fundamental")
            self.assertEqual(social["execution_mode"], "in_process")
            self.assertEqual(social["status"], "result_ready")
            self.assertEqual(social["result_post_count"], 2)
            self.assertEqual(ownership["execution_mode"], "in_process")
            self.assertEqual(ownership["status"], "result_ready")
            self.assertGreaterEqual(ownership["result_evidence_count"], 1)

            self.assertEqual(len(x_calls), 1)
            self.assertEqual(x_calls[0]["topic"], "A-share social evidence 2025-09-30")
            self.assertEqual(len(bundle_calls), 1)
            argv = bundle_calls[0]
            self.assertIn("--output", argv)
            self.assertIn("--source-capabilities", argv)
            self.assertIn("--analysis-date", argv)

    def test_runner_exception_records_execution_error(self) -> None:
        with _tempdir() as tmp:
            package = _base_package()

            def x_runner(payload: dict) -> dict:
                raise RuntimeError("session boot failed")

            def bundle_runner(argv: list[str]) -> int:
                raise SystemExit(2)

            followups = write_institutional_evidence_followup_requests(
                package,
                shortlist_result=None,
                output_root=tmp,
                execute=True,
                x_index_runner=x_runner,
                evidence_bundle_runner=bundle_runner,
            )

            social = _by_id(followups, "social_altdata")
            ownership = _by_id(followups, "ownership_fundamental")
            self.assertEqual(social["status"], "execution_error")
            self.assertIn("RuntimeError", social["execution_error"])
            self.assertEqual(ownership["status"], "execution_error")
            self.assertIn("SystemExit", ownership["execution_error"])


class BuildOwnershipFundamentalArgvTests(unittest.TestCase):
    def test_argv_contains_expected_flags(self) -> None:
        with _tempdir() as tmp:
            payload = {
                "output_path": str(tmp / "bundle.json"),
                "markdown_output_path": str(tmp / "bundle.md"),
                "target_date": "2025-09-30",
                "sec_tickers": ["AAPL", "MSFT"],
            }
            stock_path = tmp / "stock.json"
            stock_path.write_text("{}", encoding="utf-8")
            argv = build_ownership_fundamental_argv(payload, stock_input_paths=[stock_path])
        self.assertIn("--output", argv)
        self.assertIn("--markdown-output", argv)
        self.assertIn("--analysis-date", argv)
        self.assertEqual(argv.count("--sec-ticker"), 2)
        self.assertIn("--eastmoney-notice-stock", argv)
        self.assertIn("--akshare-fundamental-stock", argv)
        self.assertIn("--refresh-eastmoney-notices", argv)
        self.assertIn("--source-capabilities", argv)


class RefreshFollowupResultStateTests(unittest.TestCase):
    def test_empty_x_index_result_marks_empty_result(self) -> None:
        with _tempdir() as tmp:
            result_path = tmp / "x-index-result.json"
            result_path.write_text(json.dumps({"x_posts": []}), encoding="utf-8")
            followup = {
                "id": "social_altdata",
                "expected_result_path": str(result_path),
                "status": "request_ready",
            }
            refresh_institutional_evidence_followup_result_state(followup)
        self.assertEqual(followup["status"], "empty_result")
        self.assertEqual(followup["result_post_count"], 0)

    def test_stale_only_x_index_result_surfaces_background_post_count(self) -> None:
        with _tempdir() as tmp:
            result_path = tmp / "x-index-result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "x_posts": [],
                        "background_x_posts": [
                            {"author_handle": "trusted", "freshness_status": "stale"},
                            {"author_handle": "slow_feed", "freshness_status": "unknown"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            followup = {
                "id": "social_altdata",
                "expected_result_path": str(result_path),
                "status": "request_ready",
            }
            refresh_institutional_evidence_followup_result_state(followup)
        self.assertEqual(followup["status"], "empty_result")
        self.assertEqual(followup["result_post_count"], 0)
        self.assertEqual(followup["background_post_count"], 2)
        self.assertIn("background/stale", followup["result_note"])

    def test_empty_x_index_result_clears_stale_background_post_count(self) -> None:
        with _tempdir() as tmp:
            result_path = tmp / "x-index-result.json"
            result_path.write_text(json.dumps({"x_posts": [], "background_x_posts": []}), encoding="utf-8")
            followup = {
                "id": "social_altdata",
                "expected_result_path": str(result_path),
                "status": "empty_result",
                "background_post_count": 3,
                "result_note": "old background/stale note",
            }
            refresh_institutional_evidence_followup_result_state(followup)
        self.assertEqual(followup["status"], "empty_result")
        self.assertEqual(followup["result_post_count"], 0)
        self.assertNotIn("background_post_count", followup)
        self.assertEqual(followup["result_note"], "x-index ran, but returned zero posts; keep social_altdata unresolved.")


class WritePackageReRunsAuditTests(unittest.TestCase):
    def test_followup_execution_triggers_audit_rerun_with_new_evidence(self) -> None:
        with _tempdir() as tmp:
            audit_calls: list[dict] = []

            def audit_runner(payload: dict) -> dict:
                audit_calls.append(payload)
                external_evidence = payload.get("external_evidence") or []
                upgrade = []
                if not any("x_posts" in row for row in external_evidence):
                    upgrade.append({"id": "social_altdata"})
                if not any("filings" in row for row in external_evidence):
                    upgrade.append({"id": "ownership_fundamental"})
                return {
                    "schema_version": "institutional_signal_audit/v1",
                    "status": "institutional_ready" if not upgrade else "research_grade_partial",
                    "score": 100.0 if not upgrade else 88.0,
                    "max_score": 100.0,
                    "upgrade_priorities": upgrade,
                    "layers": [],
                }

            def shortlist_runner(request: dict) -> dict:
                return {
                    "top_picks": [{"ticker": "AAPL.US", "name": "Apple"}],
                    "schema_version": "month_end_shortlist/v1",
                }

            def postclose_runner(shortlist_result: dict, trade_date: str, plan_md: str) -> dict:
                return {"schema_version": "postclose_review/v1", "review_checklist": ["ok"]}

            def x_runner(payload: dict) -> dict:
                output_dir = Path(payload["output_dir"])
                output_dir.mkdir(parents=True, exist_ok=True)
                result = {
                    "schema_version": "x-index/v1",
                    "x_posts": [
                        {"author_handle": "alice", "post_url": "https://x.com/alice/1"},
                        {"author_handle": "bob", "post_url": "https://x.com/bob/2"},
                    ],
                }
                (output_dir / "x-index-result.json").write_text(
                    json.dumps(result, ensure_ascii=False), encoding="utf-8"
                )
                (output_dir / "x-index-report.md").write_text("# x-index report\n", encoding="utf-8")
                return result

            def bundle_runner(argv: list[str]) -> int:
                output_index = argv.index("--output")
                output_path = Path(argv[output_index + 1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                bundle = {
                    "schema_version": "institutional-evidence-bundle/v1",
                    "summary": {"filing_count": 2, "fundamental_report_count": 1, "ownership_record_count": 0},
                    "filings": [{"ticker": "AAPL", "form": "10-Q"}, {"ticker": "AAPL", "form": "8-K"}],
                    "fundamentals": {"reports": [{"ticker": "600519"}]},
                }
                output_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
                md_index = argv.index("--markdown-output")
                Path(argv[md_index + 1]).write_text("# bundle\n", encoding="utf-8")
                return 0

            output_dir = tmp / "run-root" / "html"
            output_dir.mkdir(parents=True, exist_ok=True)
            pool = {
                "name": "verify-pool",
                "stocks": [
                    {"ticker": "AAPL.US", "name": "Apple", "plan_snapshot": {"chain_name": "Consumer Electronics"}},
                    {"ticker": "600519.SH", "name": "Kweichow Moutai", "plan_snapshot": {"chain_name": "Liquor"}},
                ],
            }

            from unittest.mock import patch

            with (
                patch(
                    "local_stock_pool_manager_runtime.default_x_index_runner",
                    side_effect=x_runner,
                ),
                patch(
                    "local_stock_pool_manager_runtime.default_evidence_bundle_runner",
                    side_effect=bundle_runner,
                ),
            ):
                package = write_local_stock_pool_manager_package(
                    pool,
                    output_dir=output_dir,
                    target_date="2025-09-30",
                    analysis_time="2025-09-30T16:00:00",
                    run_shortlist=True,
                    shortlist_runner=shortlist_runner,
                    run_postclose_review=True,
                    postclose_review_runner=postclose_runner,
                    institutional_audit_runner=audit_runner,
                    auto_discover_institutional_evidence=False,
                    execute_institutional_evidence_followups=True,
                )

            self.assertGreaterEqual(len(audit_calls), 2)
            second_payload = audit_calls[1]
            external = second_payload.get("external_evidence") or []
            self.assertTrue(any("x_posts" in row for row in external))
            self.assertTrue(any("filings" in row for row in external))
            audit_result = package.get("institutional_signal_audit") or {}
            self.assertEqual(audit_result.get("status"), "institutional_ready")
            self.assertEqual(audit_result.get("score"), 100.0)
            self.assertEqual(audit_result.get("upgrade_priorities"), [])
            followups = package.get("institutional_evidence_followups") or []
            statuses = {row["id"]: row["status"] for row in followups}
            self.assertEqual(statuses["social_altdata"], "result_ready")
            self.assertEqual(statuses["ownership_fundamental"], "result_ready")


def _by_id(rows: list[dict], identifier: str) -> dict:
    for row in rows:
        if row.get("id") == identifier:
            return row
    raise AssertionError(f"followup {identifier!r} not found")


class _tempdir:
    def __enter__(self) -> Path:
        import tempfile

        self._dir = tempfile.TemporaryDirectory()
        return Path(self._dir.name).resolve()

    def __exit__(self, exc_type, exc, tb) -> None:
        self._dir.cleanup()


if __name__ == "__main__":
    unittest.main()
