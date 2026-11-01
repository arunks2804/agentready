# Notifications Service

Sends transactional email and SMS on behalf of product teams. Product teams call
one endpoint with a template name and the fields it needs. This service renders
the message, picks the delivery channel and retries failed webhook callbacks.

## Setup

Python 3.11 or later. There are no third-party dependencies.

## Adding a template

A new template must be registered in three places:

1. `TEMPLATE_BODIES` in `src/notifications/templates.py`: the message text.
2. `REQUIRED_FIELDS` in `src/notifications/templates.py`: the fields it needs.
3. `TEMPLATE_CHANNELS` in `src/notifications/dispatcher.py`: email or sms.

Also add the template to the `template` enum in `openapi.yaml`.
