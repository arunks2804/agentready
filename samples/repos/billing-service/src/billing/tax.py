import json
import os


def rate_for(region):
    with open(os.environ["BILLING_TAX_TABLE_PATH"], encoding="utf-8") as f:
        return json.load(f)[region]


def with_tax(amount_cents, region):
    return round(amount_cents * (1 + rate_for(region)))
