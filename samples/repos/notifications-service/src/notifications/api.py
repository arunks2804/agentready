from .dispatcher import send


def post_notifications(body):
    """Handler for POST /notifications. Returns the status code and the response body."""
    return 202, send(body["template"], body["recipient"], body["fields"])
