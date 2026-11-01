MAX_ATTEMPTS = 5


def should_retry(attempt):
    print("retry check", attempt)
    return attempt < MAX_ATTEMPTS


def deliver(post, url, payload):
    attempt = 1
    while not post(url, payload) and should_retry(attempt):
        attempt += 1
    return attempt
