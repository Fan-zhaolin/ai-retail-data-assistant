import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


class DatabaseInitializationTests(unittest.TestCase):
    def test_ensure_database_publishes_a_queryable_database(self):
        from src import db

        sample = pd.DataFrame(
            {
                "transaction_id": ["T001"],
                "transaction_date": pd.to_datetime(["2025-01-01"]),
                "customer_id": ["C001"],
                "customer_gender": ["Female"],
                "customer_age_group": ["25-34"],
                "customer_segment": ["VIP"],
                "product_id": ["P001"],
                "product_name": ["Sample Product"],
                "category": ["Beauty"],
                "brand": ["Sample Brand"],
                "unit_price": [100.0],
                "quantity": [2],
                "discount_pct": [0],
                "sales_amount": [200.0],
                "payment_method": ["Card"],
                "sales_channel": ["Online"],
                "region": ["Beijing"],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "app.db"
            with patch.object(db, "DB_PATH", db_path), patch.object(
                db, "load_raw_data", return_value=sample
            ):
                db.ensure_database()

                self.assertTrue(db.database_is_ready())
                result = db.run_sql("SELECT SUM(sales_amount) AS total FROM fact_sales")
                self.assertEqual(float(result.loc[0, "total"]), 200.0)
                self.assertEqual(list(db_path.parent.glob("app.db.*.tmp")), [])
