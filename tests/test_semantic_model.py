import json
import tempfile
import unittest
from pathlib import Path


class SemanticModelTests(unittest.TestCase):
    def test_default_model_builds_prompt_context(self):
        from src.semantic_model import build_semantic_context, load_semantic_model

        context = build_semantic_context(load_semantic_model())
        self.assertIn("fact_sales", context)
        self.assertIn("净销售额", context)
        self.assertIn("库存", context)

    def test_missing_metrics_is_rejected(self):
        from src.semantic_model import load_semantic_model

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.json"
            path.write_text(
                json.dumps(
                    {
                        "tables": {"fact_sales": {"columns": {"id": "编号"}}},
                        "joins": [],
                        "field_constraints": [],
                        "synonyms": {},
                        "unsupported_fields": [],
                        "query_rules": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "metrics"):
                load_semantic_model(path)

    def test_join_to_unknown_column_is_rejected(self):
        from src.semantic_model import validate_semantic_model

        model = {
            "tables": {"fact_sales": {"columns": {"product_id": "商品编号"}}},
            "joins": [{"left": "fact_sales.product_id", "right": "fact_sales.missing"}],
            "metrics": {"订单数": "COUNT(*)"},
            "field_constraints": [],
            "synonyms": {},
            "unsupported_fields": [],
            "query_rules": [],
        }
        with self.assertRaisesRegex(ValueError, "关联字段不存在"):
            validate_semantic_model(model)


if __name__ == "__main__":
    unittest.main()
