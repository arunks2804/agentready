import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from identity.accounts import lookup, token_ttl


class LookupTest(unittest.TestCase):
    def test_lookup_ignores_email_case(self):
        self.assertEqual(lookup("A@Example.com "), "acc_1")

    def test_token_ttl_configured(self):
        self.assertEqual(token_ttl(), 900)


if __name__ == "__main__":
    unittest.main()
