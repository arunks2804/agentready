# billing-service

Owns invoice generation, subscription changes, mid-cycle proration and tax
calculation for all paid plans. Other services call it over HTTP; it does not
call back into them. Amounts are always integer cents.

## Setup

Python 3.11+. No third-party runtime dependencies.

## Running tests

```
python -m unittest discover -s tests
```
