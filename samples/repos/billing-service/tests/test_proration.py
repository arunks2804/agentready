import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from billing.proration import prorate
from billing.tax import with_tax


class ProrationTest(unittest.TestCase):
    def test_rounds_to_nearest_cent(self):
        self.assertEqual(prorate(1000, 2, 3), 667)

    def test_prorated_total_includes_tax(self):
        self.assertEqual(with_tax(prorate(1000, 2, 3), "CA"), 717)


if __name__ == "__main__":
    unittest.main()
