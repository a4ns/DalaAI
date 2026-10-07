"""Static fixture conformance to the real parser; NOT HTTP/database acceptance."""
import unittest

from app.orders.validation import parse_command
from vertical_acceptance.fixtures import CODE, command, create_order_command, submission_payload


class FixtureContractTests(unittest.TestCase):
    def test_every_lifecycle_request_parses(self):
        intents = [create_order_command("planned"), create_order_command("unplanned"),
                   command("accept", 1), command("start", 2), command("pause", 3, {"reason": "Synthetic pause"}),
                   command("change_priority", 3, {"priority": "high", "reason": "Synthetic draft"}),
                   command("resume", 4), command("submit", 5, submission_payload()),
                   command("review", 6, {"submission_id": CODE, "decision": "close", "reason": "Synthetic review", "final_score": None}),
                   command("review", 4, {"submission_id": CODE, "decision": "rework", "reason": "Required evidence", "final_score": None})]
        for intent in intents:
            with self.subTest(action=intent["action"]):
                parsed = parse_command(intent)
                self.assertEqual(parsed.operation_id, intent["operation_id"])


if __name__ == "__main__":
    unittest.main()
