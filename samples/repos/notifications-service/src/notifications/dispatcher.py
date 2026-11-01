from .templates import render

TEMPLATE_CHANNELS = {
    "welcome": "email",
    "password_reset": "email",
    "login_code": "sms",
}

_sequence = 0


def send(template, recipient, fields):
    global _sequence
    channel = TEMPLATE_CHANNELS[template]
    body = render(template, fields)
    _sequence += 1
    return {"delivery_id": f"d_{_sequence}", "channel": channel, "recipient": recipient, "body": body}
