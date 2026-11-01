"""Minimal client for a local Ollama server. Nothing here leaves the machine."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


class OllamaError(RuntimeError):
    pass


def is_local(url):
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and parts.hostname in LOCAL_HOSTS


def _request(base_url, path, body=None, timeout=10):
    if not is_local(base_url):
        raise OllamaError("Ollama must run on this machine, so source code never leaves it.")
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base_url.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise OllamaError(f"Ollama returned {error.code}: {error.read().decode(errors='replace')[:300]}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise OllamaError(f"Could not reach Ollama at {base_url}: {error}") from error


def installed_models(base_url):
    """Whatever is really installed. Only models that can call tools can act as an agent."""
    models = []
    for row in _request(base_url, "/api/tags").get("models", []):
        capabilities = row.get("capabilities") or []
        details = row.get("details") or {}
        models.append({
            "name": row["name"], "family": details.get("family"), "size": details.get("parameter_size"),
            "capabilities": capabilities, "usable": "tools" in capabilities,
        })
    return models


def chat(settings, model, messages, tools, schema=None):
    body = {
        "model": model, "messages": messages, "tools": tools, "stream": False, "keep_alive": "15m",
        "options": {"num_ctx": settings["num_ctx"], "num_predict": settings["num_predict"], "temperature": 0.1},
    }
    if schema:
        body["format"] = schema
    if settings.get("think") is not None:
        body["think"] = settings["think"]
    return _request(settings["base_url"], "/api/chat", body, timeout=settings["timeout_s"])
