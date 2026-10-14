"""Guardrails: rate limits, input checks, moderation, leak detection."""
import threading
import time
import unicodedata
from collections import defaultdict, deque

from . import config
from .prompts import CANARY


class RateLimiter:
    """Sliding-window limiter keyed by e.g. client IP. In-memory: one instance per process."""

    def __init__(self, limit, window_s):
        self.limit, self.window = limit, window_s
        self.hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key):
        now = time.monotonic()
        with self._lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self.hits) > 50_000:          # keep memory bounded
                self.hits = defaultdict(deque, {k: v for k, v in self.hits.items() if v})
            return True


message_limiter = RateLimiter(config.MESSAGES_PER_MINUTE_PER_IP, 60)
session_limiter = RateLimiter(config.SESSIONS_PER_HOUR_PER_IP, 3600)


def clean_input(text):
    """Normalise and strip control characters; return (text, error)."""
    if not isinstance(text, str):
        return None, "Please send a text message."
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C").strip()
    if not text:
        return None, "Type a message to continue."
    if len(text) > config.MAX_INPUT_CHARS:
        return None, f"Messages are limited to {config.MAX_INPUT_CHARS} characters. Shorten it and send again."
    return text, None


def is_flagged(client, text):
    """Moderation check. Fails open (returns False) if the endpoint is unavailable."""
    try:
        res = client.moderations.create(model=config.MODERATION_MODEL, input=text)
        return bool(res.results[0].flagged)
    except Exception:
        return False


def leaked(text):
    return bool(text) and CANARY in text
