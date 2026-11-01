# Notifications Service

Sends transactional email and SMS on behalf of product teams. Product teams call
one endpoint with a template name and the fields it needs. This service renders
the message, picks the delivery channel and retries failed webhook callbacks.

## Setup

Python 3.11 or later. There are no third-party dependencies.

## Adding a template

Add the template text to `TEMPLATE_BODIES` in `src/notifications/templates.py`.
That is the only change needed. The dispatcher picks up new templates automatically.
