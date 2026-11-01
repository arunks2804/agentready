import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from notifications.dispatcher import TEMPLATE_CHANNELS, send
from notifications.templates import REQUIRED_FIELDS, TEMPLATE_BODIES, render


class TemplateTest(unittest.TestCase):
    def test_render_fills_fields(self):
        self.assertIn("Ann", render("welcome", {"name": "Ann"}))

    def test_missing_field_is_rejected(self):
        with self.assertRaises(ValueError):
            render("password_reset", {"name": "Ann"})

    def test_login_code_goes_by_sms(self):
        self.assertEqual(send("login_code", "+15550100", {"code": "4411"})["channel"], "sms")

    def test_every_template_is_fully_registered(self):
        self.assertEqual(set(TEMPLATE_BODIES), set(REQUIRED_FIELDS))
        self.assertEqual(set(TEMPLATE_BODIES), set(TEMPLATE_CHANNELS))


if __name__ == "__main__":
    unittest.main()
