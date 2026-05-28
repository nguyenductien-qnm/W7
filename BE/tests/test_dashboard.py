import importlib
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

core = types.ModuleType("core")
core.get_session_id = lambda event: (event.get("queryStringParameters") or {}).get("session_id", "")
core.get_user_id = lambda event: (event.get("queryStringParameters") or {}).get("user_id", "demo")
core.list_user_items = lambda _user_id: []
core.response = lambda status_code, body: {"statusCode": status_code, "body": body}
sys.modules["core"] = core

tool_contract = types.ModuleType("tool_contract")
tool_contract.is_tool_event = lambda _event: False
tool_contract.parse_http_response = lambda response: (response["statusCode"], response["body"])
tool_contract.tool_name_from_event = lambda _event, default=None: default
tool_contract.tool_payload = lambda event: event
tool_contract.tool_response = lambda name, status, data=None, errors=None: {
    "tool_name": name,
    "status": status,
    "data": data or {},
    "errors": errors or [],
}
sys.modules["tool_contract"] = tool_contract

history_lambda = importlib.import_module("history.history_lambda")


class DashboardAggregationTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)

    def dashboard(self, items, session_id="all", days=7):
        return history_lambda._dashboard_from_items(items, "demo", session_id, days, now=self.now)

    def test_filters_to_window(self):
        result = self.dashboard(
            [
                {
                    "SK": "QUESTION#2026-05-27T10:00:00Z#abc",
                    "session_id": "default",
                    "topic": "CAP theorem",
                    "created_at": "2026-05-27T10:00:00Z",
                },
                {
                    "SK": "QUESTION#2026-05-01T10:00:00Z#abc",
                    "session_id": "default",
                    "topic": "Old topic",
                    "created_at": "2026-05-01T10:00:00Z",
                },
            ]
        )
        self.assertEqual([topic["topic"] for topic in result["topics"]], ["CAP theorem"])
        self.assertEqual(result["totals"]["questions"], 1)

    def test_aggregates_summary_quiz_qa_and_planner(self):
        result = self.dashboard(
            [
                {
                    "SK": "DOC#d1#SUMMARY#TS#2026-05-27T10:00:00Z#abc",
                    "session_id": "default",
                    "testable_concepts": ["CAP theorem", "Replication"],
                    "generated_at": "2026-05-27T10:00:00Z",
                },
                {
                    "SK": "DOC#d1#QUIZ#TS#2026-05-28T08:00:00Z#abc",
                    "session_id": "default",
                    "feature": "quiz",
                    "questions": [{"topic": "cap theorem"}, {"source_title": "Distributed Systems"}],
                    "generated_at": "2026-05-28T08:00:00Z",
                },
                {
                    "SK": "QUESTION#2026-05-28T09:00:00Z#abc",
                    "session_id": "default",
                    "topic": "Replication",
                    "created_at": "2026-05-28T09:00:00Z",
                },
                {
                    "SK": "EXAM_PLAN#TS#2026-05-28T11:00:00Z#plan#abc",
                    "session_id": "default",
                    "weak_topics": ["Quorum"],
                    "tasks": [{"topic": "CAP theorem"}],
                    "generated_at": "2026-05-28T11:00:00Z",
                },
            ]
        )
        topics = {item["topic"]: item for item in result["topics"]}
        self.assertEqual(result["totals"]["summaries"], 1)
        self.assertEqual(result["totals"]["quizzes"], 1)
        self.assertEqual(result["totals"]["questions"], 1)
        self.assertEqual(result["totals"]["plans"], 1)
        self.assertEqual(topics["CAP theorem"]["count"], 3)
        self.assertIn("summary", topics["CAP theorem"]["sources"])
        self.assertIn("quiz", topics["CAP theorem"]["sources"])
        self.assertIn("planning", topics["CAP theorem"]["sources"])

    def test_handles_no_activity(self):
        result = self.dashboard([])
        self.assertEqual(result["topics"], [])
        self.assertEqual(result["totals"]["topics"], 0)

    def test_respects_session_id(self):
        result = self.dashboard(
            [
                {
                    "SK": "QUESTION#2026-05-28T09:00:00Z#abc",
                    "session_id": "s1",
                    "topic": "Included",
                    "created_at": "2026-05-28T09:00:00Z",
                },
                {
                    "SK": "QUESTION#2026-05-28T09:01:00Z#abc",
                    "session_id": "s2",
                    "topic": "Excluded",
                    "created_at": "2026-05-28T09:01:00Z",
                },
            ],
            session_id="s1",
        )
        self.assertEqual([topic["topic"] for topic in result["topics"]], ["Included"])

    def test_clamps_days(self):
        self.assertEqual(history_lambda._parse_days("0"), 1)
        self.assertEqual(history_lambda._parse_days("45"), 30)
        self.assertEqual(history_lambda._parse_days("bad"), 7)


if __name__ == "__main__":
    unittest.main()
