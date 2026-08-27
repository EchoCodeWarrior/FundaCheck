"""Small regression checks for the browser-side Q&A contract.

The frontend is intentionally dependency-free, so these checks avoid pulling in
a browser test runner.  They pin the two user-visible Q&A behaviors that are
easy to regress while keeping the test independent of DOM timing and network
requests.
"""

from __future__ import annotations

from pathlib import Path
import unittest


APP_JS = Path(__file__).resolve().parents[1] / "assets" / "app.js"
STALE_DEFAULT_PROMPT = "Ask a question about the loaded company"


def _section(source: str, start_marker: str, end_marker: str) -> str:
    """Return the source between two stable frontend contract boundaries."""

    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


class FrontendQaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_JS.read_text(encoding="utf-8")

    def test_default_answer_does_not_render_stale_question_prompt(self):
        default_answer = _section(
            self.source,
            "function defaultAnswer(data) {",
            "function renderAnswer(answer)",
        )

        self.assertNotIn(STALE_DEFAULT_PROMPT, default_answer)

    def test_suggestion_click_submits_selected_question(self):
        suggestion_handler = _section(
            self.source,
            'if (action === "use-suggestion") {',
            'if (action === "ask-question") {',
        )

        self.assertIn("actionNode.dataset.question", suggestion_handler)
        self.assertRegex(suggestion_handler, r"\baskQuestion\s*\(")


if __name__ == "__main__":
    unittest.main()
