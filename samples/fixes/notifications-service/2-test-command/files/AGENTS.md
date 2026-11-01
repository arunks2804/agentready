# Agent guide

Run tests with `python -m unittest discover -s tests`.

## Adding a template

A new template must be registered in three places. All three are needed.

1. `TEMPLATE_BODIES` in `src/notifications/templates.py`
2. `REQUIRED_FIELDS` in `src/notifications/templates.py`
3. `TEMPLATE_CHANNELS` in `src/notifications/dispatcher.py`

Add tests to `tests/test_templates.py`.
