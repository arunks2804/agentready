TEMPLATE_BODIES = {
    "welcome": "Hello {name}, welcome aboard.",
    "password_reset": "Hello {name}, reset your password here: {link}",
    "login_code": "Your login code is {code}.",
}

REQUIRED_FIELDS = {
    "welcome": ("name",),
    "password_reset": ("name", "link"),
    "login_code": ("code",),
}


def render(template, fields):
    required = REQUIRED_FIELDS[template]
    missing = [name for name in required if name not in fields]
    if missing:
        raise ValueError(f"Missing fields for {template}: {', '.join(missing)}")
    return TEMPLATE_BODIES[template].format(**fields)
