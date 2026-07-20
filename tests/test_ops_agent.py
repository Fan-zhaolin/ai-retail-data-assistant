import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd


def operations_sample() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "transaction_id": ["T0000064", "T0020032", "T0074297"],
            "transaction_date": ["2025-12-14", "2025-12-30", "2024-01-01"],
            "customer_id": ["C001", "C002", "C003"],
            "customer_gender": ["Female", "Male", "Female"],
            "customer_age_group": ["25-34", "35-44", "45-54"],
            "customer_segment": ["VIP", "Regular", "Regular"],
            "product_id": ["P1025", "P1013", "P1001"],
            "product_name": ["Dress", "Bluetooth Speaker", "Smartphone"],
            "category": ["Clothing", "Electronics", "Electronics"],
            "brand": ["Brand A", "Brand B", "Brand C"],
            "unit_price": [200.0, 300.0, 500.0],
            "quantity": [1, 1, 1],
            "discount_pct": [10, 0, 0],
            "sales_amount": [180.0, 300.0, 500.0],
            "payment_method": ["Card", "Card", "Cash"],
            "sales_channel": ["Online", "Mobile App", "In-Store"],
            "region": ["North", "South", "East"],
        }
    )


class OperationsAgentTests(unittest.TestCase):
    def setUp(self):
        from src.db import build_database_from_dataframe

        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "analytics.db"
        self.action_db = Path(self.tmp.name) / "actions.db"
        build_database_from_dataframe(operations_sample(), self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_generated_database_contains_demo_operations_tables(self):
        conn = sqlite3.connect(self.db_path)
        try:
            names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        finally:
            conn.close()

        self.assertTrue({"ops_orders", "inventory_snapshot", "return_policies"}.issubset(names))

    def test_order_lookup_uses_read_only_operations_data(self):
        from src.ops_agent import run_ops_agent

        result = run_ops_agent(
            "订单 T0000064 到哪了？",
            db_path=self.db_path,
            action_db_path=self.action_db,
            session_id="test",
        )

        self.assertEqual(result["route"], "order_lookup")
        self.assertEqual(result["order"]["order_status"], "Delivered")
        self.assertFalse(result["requires_approval"])

    def test_inventory_lookup_reports_threshold_and_status(self):
        from src.ops_agent import run_ops_agent

        result = run_ops_agent(
            "P1025 当前库存是否需要补货？",
            db_path=self.db_path,
            action_db_path=self.action_db,
            session_id="test",
        )

        self.assertEqual(result["route"], "inventory_lookup")
        self.assertEqual(result["items"][0]["product_id"], "P1025")
        self.assertIn("reorder_point", result["items"][0])

    def test_policy_question_is_not_misrouted_as_return_request(self):
        from src.ops_agent import run_ops_agent

        result = run_ops_agent(
            "电子产品退货政策是什么？",
            db_path=self.db_path,
            action_db_path=self.action_db,
            session_id="test",
        )

        self.assertEqual(result["route"], "return_policy")
        self.assertEqual(result["policies"][0]["category"], "Electronics")

    def test_eligible_return_stops_before_write(self):
        from src.ops_agent import run_ops_agent

        result = run_ops_agent(
            "订单 T0000064 想退货，原因是尺寸不合适",
            db_path=self.db_path,
            action_db_path=self.action_db,
            session_id="test",
        )

        self.assertEqual(result["route"], "return_request")
        self.assertTrue(result["requires_approval"])
        self.assertEqual(result["trace"][-1]["status"], "waiting_approval")
        conn = sqlite3.connect(self.action_db)
        try:
            count = conn.execute("SELECT COUNT(*) FROM return_requests").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)

    def test_write_requires_explicit_approval(self):
        from src.ops_agent import execute_return_request, prepare_return_request

        proposal = prepare_return_request("T0000064", "尺寸不合适", self.db_path)
        with self.assertRaises(PermissionError):
            execute_return_request(
                proposal,
                approved=False,
                action_db_path=self.action_db,
                session_id="test",
            )

    def test_approved_return_is_idempotent(self):
        from src.ops_agent import execute_return_request, prepare_return_request

        proposal = prepare_return_request("T0000064", "尺寸不合适", self.db_path)
        first = execute_return_request(
            proposal,
            approved=True,
            action_db_path=self.action_db,
            session_id="test",
        )
        second = execute_return_request(
            proposal,
            approved=True,
            action_db_path=self.action_db,
            session_id="test",
        )

        self.assertEqual(first["request_id"], second["request_id"])
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])

    def test_old_order_is_outside_return_window(self):
        from src.ops_agent import prepare_return_request

        proposal = prepare_return_request("T0074297", "不再需要", self.db_path)

        self.assertFalse(proposal["eligible"])
        self.assertIn("超过", proposal["eligibility"]["reason"])

    def test_undelivered_order_cannot_start_return(self):
        from src.ops_agent import prepare_return_request

        proposal = prepare_return_request("T0020032", "不再需要", self.db_path)

        self.assertFalse(proposal["eligible"])
        self.assertIn("尚未送达", proposal["eligibility"]["reason"])

    def test_audit_log_records_tool_route_and_status(self):
        from src.ops_agent import read_audit_events, run_ops_agent

        run_ops_agent(
            "订单 T0000064 到哪了？",
            db_path=self.db_path,
            action_db_path=self.action_db,
            session_id="audit-session",
        )
        events = read_audit_events(self.action_db, "audit-session")

        self.assertEqual(events[0]["route"], "order_lookup")
        self.assertEqual(events[0]["tool_name"], "query_order")
        self.assertEqual(events[0]["status"], "success")

    def test_unknown_task_asks_for_clarification(self):
        from src.ops_agent import run_ops_agent

        result = run_ops_agent(
            "帮我把这个月业务都处理好",
            db_path=self.db_path,
            action_db_path=self.action_db,
            session_id="test",
        )

        self.assertEqual(result["route"], "clarification")
        self.assertEqual(result["trace"][0]["status"], "needs_input")


if __name__ == "__main__":
    unittest.main()
