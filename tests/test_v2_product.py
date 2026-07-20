import tempfile
import unittest
from pathlib import Path

import pandas as pd


def sample_sales() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "transaction_id": ["T001", "T002", "T003", "T004"],
            "transaction_date": ["2025-01-15", "2025-01-20", "2025-02-10", "2025-02-12"],
            "customer_id": ["C001", "C002", "C001", "C003"],
            "customer_gender": ["Female", "Male", "Female", "Male"],
            "customer_age_group": ["25-34", "35-44", "25-34", "18-24"],
            "customer_segment": ["VIP", "Regular", "VIP", "Regular"],
            "product_id": ["P001", "P002", "P001", "P002"],
            "product_name": ["A", "B", "A", "B"],
            "category": ["Beauty", "Electronics", "Beauty", "Electronics"],
            "brand": ["Brand A", "Brand B", "Brand A", "Brand B"],
            "unit_price": [100.0, 200.0, 100.0, 200.0],
            "quantity": [1, 1, 2, 1],
            "discount_pct": [0, 0, 0, 10],
            "sales_amount": [100.0, 200.0, 200.0, 180.0],
            "payment_method": ["Card", "Cash", "Card", "Card"],
            "sales_channel": ["Online", "In-Store", "Online", "In-Store"],
            "region": ["North", "South", "North", "South"],
        }
    )


class V2ProductTests(unittest.TestCase):
    def test_chinese_sales_columns_are_adapted(self):
        from src.data_adapter import adapt_source_dataframe
        from src.db import REQUIRED_COLUMNS

        source = pd.DataFrame(
            {
                "订单号": ["O001"],
                "交易日期": ["2025-03-01"],
                "品类": ["美妆"],
                "销售渠道": ["线上"],
                "销售额": [299.0],
                "数量": [1],
            }
        )
        adapted, report = adapt_source_dataframe(source)

        self.assertTrue(set(REQUIRED_COLUMNS).issubset(adapted.columns))
        self.assertEqual(float(adapted.loc[0, "sales_amount"]), 299.0)
        self.assertTrue(str(adapted.loc[0, "product_id"]).startswith("AUTO-P"))
        self.assertEqual(report["mapping"]["sales_amount"], "销售额")

    def test_same_schema_data_builds_isolated_database(self):
        from src.db import build_database_from_dataframe, run_sql

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "session" / "app.db"
            metadata = build_database_from_dataframe(sample_sales(), db_path)
            result = run_sql("SELECT SUM(sales_amount) AS total FROM fact_sales", db_path)

        self.assertEqual(metadata["rows"], 4)
        self.assertEqual(float(result.loc[0, "total"]), 680.0)

    def test_missing_upload_column_is_rejected(self):
        from src.db import validate_source_dataframe

        frame = sample_sales().drop(columns=["sales_amount"])
        with self.assertRaisesRegex(ValueError, "sales_amount"):
            validate_source_dataframe(frame)

    def test_executive_brief_uses_latest_two_months(self):
        from src.db import build_database_from_dataframe
        from src.insights import get_executive_brief

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.db"
            build_database_from_dataframe(sample_sales(), db_path)
            brief = get_executive_brief(db_path)

        self.assertEqual(brief["latest_month"], "2025-02")
        self.assertEqual(brief["order_count"], 4)
        self.assertAlmostEqual(brief["month_change_pct"], 26.666666, places=4)
        self.assertEqual(brief["top_channel"], "Online")

    def test_followups_expand_the_current_analysis(self):
        from src.followups import suggest_followups

        questions = suggest_followups(
            "哪个品类销售额最高？",
            ["category", "net_sales"],
            {"category": "Beauty"},
        )
        self.assertEqual(len(questions), 3)
        self.assertTrue(all("美妆" in question for question in questions))
        self.assertTrue(any("渠道" in question for question in questions))
        self.assertTrue(any("趋势" in question for question in questions))

    def test_followups_use_returned_channel_before_question_keywords(self):
        from src.followups import suggest_followups

        questions = suggest_followups(
            "美妆品类在哪个销售渠道表现最好？",
            ["sales_channel", "net_sales"],
            {"sales_channel": "In-Store"},
        )
        self.assertTrue(all("线下门店" in question for question in questions))
        self.assertTrue(any("品类贡献" in question for question in questions))

    def test_channel_why_question_checks_the_premise(self):
        from src.db import build_database_from_dataframe
        from src.diagnostics import diagnose_channel_performance

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.db"
            build_database_from_dataframe(sample_sales(), db_path)
            analysis = diagnose_channel_performance("为什么表现最差的渠道是线上？", db_path)

        self.assertIsNotNone(analysis)
        self.assertIn("前提", analysis["explanation"])
        self.assertIn("不能证明", analysis["explanation"])
        self.assertEqual(analysis["diagnostic_type"], "channel_performance")

    def test_trend_summary_uses_actual_peak_and_latest_values(self):
        from src.result_summary import summarize_result

        frame = pd.DataFrame(
            {
                "year_month": ["2025-07", "2025-09", "2025-12"],
                "sales_channel": ["Online", "Online", "Online"],
                "net_sales": [661000, 629000, 643000],
            }
        )

        summary = summarize_result("网页端趋势如何", frame)

        self.assertIn("2025年07月", summary)
        self.assertIn("峰值", summary)
        self.assertIn("66.1 万元", summary)
        self.assertIn("2025年12月", summary)
        self.assertIn("64.3 万元", summary)
        self.assertIn("不能证明", summary)


if __name__ == "__main__":
    unittest.main()
