# identity-service

Owns login, account lookup and session issue for every product surface. Email
addresses are the account key, so all lookups go through one normalisation
function. Sessions are stateless signed tokens with a short expiry.

## Setup

Python 3.11+. Copy `.env.example` to `.env`.

## Running tests

```
python -m unittest discover -s tests
```
