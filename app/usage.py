"""Token usage and cost accounting (per session and per day for the whole deployment)."""
import threading
from datetime import date

from . import config


def text_cost(model, usage):
    prices = _lookup(config.TEXT_PRICES, model)
    if not prices or usage is None:
        return 0.0
    p_in, p_cached, p_write, p_out = prices
    inp = getattr(usage, "input_tokens", 0) or 0
    details = getattr(usage, "input_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) or 0
    written = getattr(details, "cache_write_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    fresh = max(inp - cached - written, 0)
    return (fresh * p_in + cached * p_cached + written * p_write + out * p_out) / 1e6


def image_cost(model, usage):
    prices = _lookup(config.IMAGE_PRICES, model)
    if not prices or usage is None:
        return config.IMAGE_FALLBACK_COST
    p_in, p_out = prices
    return ((getattr(usage, "input_tokens", 0) or 0) * p_in
            + (getattr(usage, "output_tokens", 0) or 0) * p_out) / 1e6


def _lookup(table, model):
    if model in table:
        return table[model]
    matches = [m for m in table if model.startswith(m)]   # dated snapshots
    return table[max(matches, key=len)] if matches else None


class DailyBudget:
    """Stops the whole deployment once today's spend passes DAILY_BUDGET_USD."""

    def __init__(self):
        self._lock = threading.Lock()
        self.day, self.spent = date.today(), 0.0

    def add(self, usd):
        with self._lock:
            if date.today() != self.day:
                self.day, self.spent = date.today(), 0.0
            self.spent += usd

    def exhausted(self):
        with self._lock:
            return date.today() == self.day and self.spent >= config.DAILY_BUDGET_USD


DAILY = DailyBudget()


class UsageTracker:
    def __init__(self):
        self.calls = []

    def add_text(self, label, model, usage, latency, extra_usd=0.0):
        usd = text_cost(model, usage) + extra_usd
        self.calls.append({
            "label": label, "model": model, "latency_s": round(latency, 2),
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "cost_usd": usd,
        })
        DAILY.add(usd)

    def add_image(self, model, usage, latency):
        usd = image_cost(model, usage)
        self.calls.append({"label": "image", "model": model, "latency_s": round(latency, 2),
                           "input_tokens": getattr(usage, "input_tokens", 0) or 0,
                           "output_tokens": getattr(usage, "output_tokens", 0) or 0,
                           "cost_usd": usd})
        DAILY.add(usd)

    @property
    def cost_usd(self):
        return sum(c["cost_usd"] for c in self.calls)

    def summary(self):
        usd = self.cost_usd
        by_model = {}
        for c in self.calls:
            m = by_model.setdefault(c["model"], {"calls": 0, "cost_usd": 0.0})
            m["calls"] += 1
            m["cost_usd"] = round(m["cost_usd"] + c["cost_usd"], 5)
        return {
            "input_tokens": sum(c["input_tokens"] for c in self.calls),
            "output_tokens": sum(c["output_tokens"] for c in self.calls),
            "cost_usd": round(usd, 5),
            "cost_eur": round(usd * config.EUR_PER_USD, 5),
            "by_model": by_model,
        }
