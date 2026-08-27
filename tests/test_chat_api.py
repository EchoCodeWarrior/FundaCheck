"""Regression tests for the Flask chat contract.

These tests never call xAI.  The provider request is intercepted with a fake
OpenAI-compatible response, while the route and frontend-facing JSON contract
are exercised through Flask's test client.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch


# app.py loads .env at import time.  Override it in this test process so no real
# credential can ever be used by the mocked provider test.
os.environ["LLM_PROVIDER"] = "xai"
os.environ["XAI_API_KEY"] = "unit-test-key"

import app as app_module  # noqa: E402
from core import llm  # noqa: E402


class FakeResponse:
    status_code = 200
    text = ""

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Mocked Grok answer",
                    }
                }
            ]
        }


class FailedResponse:
    status_code = 401
    text = "invalid api key"


class WrappedResponse:
    status_code = 200
    text = ""

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"note":"Wrapped Grok answer"}',
                    }
                }
            ]
        }


class ChatApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        app_module.DATASETS.clear()
        self.client = app_module.app.test_client()

    def demo_dataset(self):
        response = self.client.post("/api/analyze", data={"demo": "true"})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_health_reports_grok_configuration_without_secret(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["ai"],
            {"configured": True, "provider": "xai", "model": "grok-4.3"},
        )
        self.assertNotIn("unit-test-key", response.get_data(as_text=True))

    def test_demo_to_mocked_grok_question_uses_expected_endpoint(self):
        dataset = self.demo_dataset()

        with patch.object(llm.requests, "post", return_value=FakeResponse()) as post:
            response = self.client.post(
                "/api/ask",
                json={
                    "datasetId": dataset["datasetId"],
                    "question": "What are the biggest strengths?",
                },
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertEqual(body["answer"], "Mocked Grok answer")
        self.assertFalse(body["offline"])
        self.assertEqual(body["provider"], "xai")
        self.assertEqual(body["model"], "grok-4.3")

        call = post.call_args
        self.assertEqual(call.args[0], "https://api.x.ai/v1/chat/completions")
        self.assertEqual(call.kwargs["json"]["model"], "grok-4.3")
        self.assertEqual(
            call.kwargs["headers"]["Authorization"], "Bearer unit-test-key"
        )

    def test_offline_question_still_returns_a_useful_answer(self):
        dataset = self.demo_dataset()

        with patch.dict(os.environ, {"LLM_PROVIDER": "offline"}, clear=False):
            response = self.client.post(
                "/api/ask",
                json={
                    "datasetId": dataset["datasetId"],
                    "question": "Which ratios need attention?",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["offline"])
        self.assertIsNone(body["provider"])
        self.assertTrue(body["answer"])

    def test_provider_failure_is_explicit_and_falls_back_to_local_answer(self):
        dataset = self.demo_dataset()

        with patch.object(llm.requests, "post", return_value=FailedResponse()):
            response = self.client.post(
                "/api/ask",
                json={
                    "datasetId": dataset["datasetId"],
                    "question": "What are the biggest strengths?",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["offline"])
        self.assertIsNone(body["provider"])
        self.assertFalse(body["ai"]["available"])
        self.assertIn("401", body["ai"]["error"])
        self.assertTrue(body["answer"])

    def test_json_wrapped_provider_answer_is_unwrapped(self):
        dataset = self.demo_dataset()

        with patch.object(llm.requests, "post", return_value=WrappedResponse()):
            response = self.client.post(
                "/api/ask",
                json={
                    "datasetId": dataset["datasetId"],
                    "question": "What are the biggest strengths?",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["answer"], "Wrapped Grok answer")
        self.assertFalse(body["offline"])

    def test_invalid_dataset_and_blank_question_are_rejected(self):
        missing = self.client.post(
            "/api/ask", json={"datasetId": "missing", "question": "hello"}
        )
        self.assertEqual(missing.status_code, 404)

        dataset = self.demo_dataset()
        blank = self.client.post(
            "/api/ask",
            json={"datasetId": dataset["datasetId"], "question": "  "},
        )
        self.assertEqual(blank.status_code, 400)


if __name__ == "__main__":
    unittest.main()
