import logging
import os

logger = logging.getLogger(__name__)
ACCOUNTS = {"a@example.com": "acc_1"}


def token_ttl():
    return int(os.environ["IDENTITY_TOKEN_TTL_SECONDS"])


def lookup(email):
    logger.info("account lookup")
    return ACCOUNTS.get(email)
