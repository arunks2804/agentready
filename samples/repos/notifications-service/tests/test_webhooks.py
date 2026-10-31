import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from notifications.webhooks import should_retry


class RetryTest(unittest.TestCase):
    def test_stops_after_five_attempts(self):
        self.assertTrue(should_retry(4))
        self.assertFalse(should_retry(5))


if __name__ == "__main__":
    unittest.main()
