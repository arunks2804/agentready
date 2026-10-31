MAX_ATTEMPTS = 5


def should_retry(attempt):
    print("retry check", attempt)
    return attempt < MAX_ATTEMPTS
