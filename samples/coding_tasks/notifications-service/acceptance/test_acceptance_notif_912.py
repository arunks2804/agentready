"""AgentReady's own check for NOTIF-912. The Coding Agent never sees this file."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from notifications.dispatcher import send
from notifications.templates import render


class AcceptanceTest(unittest.TestCase):
    def test_message_includes_both_fields(self):
        message = render("payment_failed", {"name": "Ann", "amount": "$42.00"})
        self.assertIn("Ann", message)
        self.assertIn("$42.00", message)

    def test_missing_amount_is_rejected(self):
        with self.assertRaises(ValueError):
            render("payment_failed", {"name": "Ann"})

    def test_dispatcher_sends_by_email(self):
        result = send("payment_failed", "ann@example.com", {"name": "Ann", "amount": "$42.00"})
        self.assertEqual(result["channel"], "email")


if __name__ == "__main__":
    unittest.main()
