"""Rule-based analysis of failed agent traces."""
import re

SIGNATURES = [
    (r"KeyError: '[A-Z][A-Z0-9_]+'|environment variable|could not be configured",
     "env_vars_documented", "build_environment", "Required configuration is unavailable"),
    (r"no matching service|could not identify the owning", "catalog_entry", "discovery",
     "Agent could not find the service"),
    (r"no openapi|no api contract|guessed the schema", "api_spec", "api_context",
     "API contract is unavailable"),
    (r"test command|how to run the tests", "test_command_documented", "testing",
     "Agent could not work out how to run tests"),
    (r"no runbook|insufficient debugging", "runbook", "debugging",
     "Not enough debugging information"),
    (r"acceptance criteria|ambiguous ticket", "issue_template", "task_context",
     "Ticket lacks enough information"),
]


def classify(events):
    """Return the first signature found, walking the trace in step order."""
    for event in events:
        text = f"{event.get('action', '')} {event.get('output', '')}"
        for pattern, check_id, dimension, label in SIGNATURES:
            if re.search(pattern, text, re.I):
                return {
                    "check_id": check_id, "dimension": dimension, "label": label,
                    "step": event.get("step"), "quote": str(event.get("output", ""))[:300],
                }
    return {"check_id": None, "dimension": None, "label": "Unclassified", "step": None, "quote": None}
