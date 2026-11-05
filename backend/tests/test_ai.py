from contextlib import redirect_stdout
from io import StringIO
import os
import unittest
from unittest.mock import patch

from backend.app import ai


class GroqConfigurationTests(unittest.TestCase):
    def test_client_strips_whitespace_and_quotes_from_api_key(self):
        for configured_key in ('  "test-key"  ', "  'test-key'  "):
            with self.subTest(configured_key=configured_key):
                with patch.dict(os.environ, {"GROQ_API_KEY": configured_key}):
                    with patch("openai.OpenAI") as openai_client:
                        ai._client()

                self.assertEqual(openai_client.call_args.kwargs["api_key"], "test-key")

    def test_client_rejects_empty_key_after_normalization(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": '  ""  '}):
            with self.assertRaises(ai.AIConfigurationError):
                ai._client()

    def test_model_defaults_when_unset_or_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ai._model(), "llama-3.3-70b-versatile")
        with patch.dict(os.environ, {"GROQ_MODEL": ""}):
            self.assertEqual(ai._model(), "llama-3.3-70b-versatile")

    def test_groq_error_logging_includes_exact_error_and_status(self):
        error = RuntimeError("authentication rejected")
        error.status_code = 401
        output = StringIO()

        with redirect_stdout(output):
            ai.log_groq_error(error)

        self.assertEqual(
            output.getvalue(),
            "[AI Error] Groq call failed: authentication rejected\n"
            "[AI Error] HTTP status code: 401\n",
        )


if __name__ == "__main__":
    unittest.main()
