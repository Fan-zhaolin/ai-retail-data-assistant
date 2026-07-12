import unittest

import pandas as pd


class SimulatedUserTests(unittest.TestCase):
    def test_security_case_does_not_call_model(self):
        from src.simulate_users import SIMULATED_CASES, run_case

        calls = {"llm": 0, "sql": 0}

        def fake_llm(_prompt):
            calls["llm"] += 1
            return "SELECT 1"

        def fake_sql(_sql):
            calls["sql"] += 1
            return pd.DataFrame({"value": [1]})

        row = run_case(SIMULATED_CASES[11], fake_llm, fake_sql, lambda question: question)
        self.assertEqual(row["status"], "pass")
        self.assertEqual(calls, {"llm": 0, "sql": 0})

    def test_normal_case_records_query_result(self):
        from src.simulate_users import SIMULATED_CASES, run_case

        row = run_case(
            SIMULATED_CASES[0],
            lambda _prompt: "SELECT 1 AS value",
            lambda _sql: pd.DataFrame({"value": [1]}),
            lambda question: question,
        )
        self.assertEqual(row["status"], "pass")
        self.assertIn("返回 1 行", row["observed"])


if __name__ == "__main__":
    unittest.main()
