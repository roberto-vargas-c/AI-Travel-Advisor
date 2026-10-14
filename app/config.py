"""All settings come from environment variables so the same image runs anywhere."""
import os


def _env(name, default):
    return os.getenv(name, default)


def _float(name, default):
    return float(os.getenv(name, default))


def _int(name, default):
    return int(os.getenv(name, default))


# --- Models ---------------------------------------------------------------
# Multi-model workflow: a cheap, fast model runs the conversation; the latest
# GPT-6 flagship-class model writes the itinerary; a GPT Image model paints it.
CHAT_MODEL = _env("CHAT_MODEL", "gpt-6-luna")
PLANNER_MODEL = _env("PLANNER_MODEL", "gpt-6.1-sol")   # swap to gpt-6-astra for max quality
IMAGE_MODEL = _env("IMAGE_MODEL", "gpt-image-2.5-flare")
MODERATION_MODEL = _env("MODERATION_MODEL", "omni-moderation-latest")

CHAT_EFFORT = _env("CHAT_EFFORT", "low")
PLANNER_EFFORT = _env("PLANNER_EFFORT", "medium")
IMAGE_QUALITY = _env("IMAGE_QUALITY", "medium")
IMAGE_SIZE = _env("IMAGE_SIZE", "1536x1024")

CHAT_WEB_SEARCH = _env("CHAT_WEB_SEARCH", "1") == "1"      # answer "what's on" questions
PLANNER_WEB_SEARCH = _env("PLANNER_WEB_SEARCH", "1") == "1"  # check events/closures for the dates

# --- Prices (USD per 1M tokens) -------------------------------------------
# (input, cached input, cache write, output). Source: OpenAI pricing page, Oct 2026.
# Only used for the cost meter - verify before relying on it.
TEXT_PRICES = {
    "gpt-6-astra": (10.00, 1.00, 12.50, 50.00),
    "gpt-6.1-sol": (2.00, 0.10, 2.50, 10.00),
    "gpt-6-sol":   (2.00, 0.10, 2.50, 10.00),
    "gpt-6-luna":  (0.10, 0.01, 0.125, 0.50),
}
# (text input, image output) per 1M tokens
IMAGE_PRICES = {
    "gpt-image-2.5-sunburst": (5.00, 30.00),
    "gpt-image-2.5-flare":    (5.00, 30.00),
    "gpt-image-2":            (2.50, 15.00),
}
WEB_SEARCH_PRICE_PER_CALL = 0.01
IMAGE_FALLBACK_COST = 0.05      # used if the API doesn't report image token usage
EUR_PER_USD = _float("EUR_PER_USD", "0.86")

# --- Guardrails ------------------------------------------------------------
MAX_INPUT_CHARS = _int("MAX_INPUT_CHARS", "1500")
MAX_TURNS_PER_SESSION = _int("MAX_TURNS_PER_SESSION", "40")
MAX_PLANS_PER_SESSION = _int("MAX_PLANS_PER_SESSION", "6")
MAX_IMAGES_PER_SESSION = _int("MAX_IMAGES_PER_SESSION", "4")
MAX_SESSION_COST_USD = _float("MAX_SESSION_COST_USD", "1.00")
DAILY_BUDGET_USD = _float("DAILY_BUDGET_USD", "10.00")   # hard stop for the whole deployment
MESSAGES_PER_MINUTE_PER_IP = _int("MESSAGES_PER_MINUTE_PER_IP", "15")
SESSIONS_PER_HOUR_PER_IP = _int("SESSIONS_PER_HOUR_PER_IP", "20")
SESSION_TTL_SECONDS = _int("SESSION_TTL_SECONDS", str(6 * 3600))
MAX_SESSIONS = _int("MAX_SESSIONS", "2000")
MAX_TRIP_DAYS = _int("MAX_TRIP_DAYS", "21")

# Summarise older turns once the history passes this many (estimated) tokens.
SUMMARY_TRIGGER_TOKENS = _int("SUMMARY_TRIGGER_TOKENS", "8000")
SUMMARY_KEEP_MESSAGES = _int("SUMMARY_KEEP_MESSAGES", "6")

DATA_DIR = _env("DATA_DIR", "/tmp/atlas-data")
MOCK = _env("ATLAS_MOCK", "0") == "1"   # run without an API key (UI testing)
