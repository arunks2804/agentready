import logging

logger = logging.getLogger(__name__)


def prorate(amount_cents, days_used, days_in_period):
    """Charge for the used part of a billing period, in whole cents."""
    logger.debug("prorating %s for %s/%s days", amount_cents, days_used, days_in_period)
    return int(amount_cents * days_used / days_in_period)
