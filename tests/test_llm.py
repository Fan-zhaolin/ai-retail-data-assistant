import os
import unittest
from unittest.mock import patch

from src.llm import ask_llm, build_client


class LlmConfigurationTests(unittest.TestCase):
    def test_missing_api_key_is_reported_when_client_is_needed(self):
        with patch.dict(os.environ, {"LLM_MODEL": "demo-model"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "LLM_API_KEY"):
                build_client()

    def test_missing_model_is_reported_before_request(self):
        with patch.dict(os.environ, {"LLM_API_KEY": "demo-key"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "LLM_MODEL"):
                ask_llm("test prompt")


if __name__ == "__main__":
    unittest.main()
