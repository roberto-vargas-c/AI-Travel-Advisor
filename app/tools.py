"""External data tools. Fixed endpoints only - the model never controls a URL."""
import re
from datetime import date, timedelta

import requests

TIMEOUT = 10
WMO = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog",
       51: "Drizzle", 53: "Drizzle", 55: "Drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
       61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
       71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow", 80: "Showers", 81: "Showers",
       82: "Heavy showers", 85: "Snow showers", 86: "Snow showers", 95: "Thunderstorms",
       96: "Thunderstorms", 99: "Thunderstorms"}


def geocode(place):
    place = (place or "").split(",")[0].strip()[:80]
    if not place:
        return None
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                     params={"name": place, "count": 1, "language": "en"}, timeout=TIMEOUT)
    r.raise_for_status()
    results = r.json().get("results")
    return results[0] if results else None


def _year_back(d):
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d - timedelta(days=365)


def get_weather(city, start_date=None, end_date=None):
    """Forecast within 16 days; otherwise last year's weather on the same dates."""
    try:
        loc = geocode(city)
        if not loc:
            return {"error": f"Unknown place '{city}'."}
        today = date.today()
        start = date.fromisoformat(start_date) if start_date else today
        end = date.fromisoformat(end_date) if end_date else start + timedelta(days=6)
        if end < start:
            return {"error": "end_date is before start_date"}
        end = min(end, start + timedelta(days=15))
        base = {"latitude": loc["latitude"], "longitude": loc["longitude"], "timezone": "auto"}
        if start >= today and end <= today + timedelta(days=15):
            kind = "forecast"
            url = "https://api.open-meteo.com/v1/forecast"
            daily = "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
            q_start, q_end = start, end
        else:
            kind = "typical (same dates last year)"
            url = "https://archive-api.open-meteo.com/v1/archive"
            daily = "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code"
            q_start, q_end = (start, end) if end < today else (_year_back(start), _year_back(end))
        r = requests.get(url, timeout=TIMEOUT, params={
            **base, "daily": daily, "start_date": q_start.isoformat(), "end_date": q_end.isoformat()})
        r.raise_for_status()
        d = r.json()["daily"]
        days = []
        for i in range(len(d["time"])):
            days.append({
                "date": (start + timedelta(days=i)).isoformat(),
                "high_c": d["temperature_2m_max"][i],
                "low_c": d["temperature_2m_min"][i],
                "rain_chance_pct": (d.get("precipitation_probability_max") or [None] * 99)[i],
                "rain_mm": (d.get("precipitation_sum") or [None] * 99)[i],
                "conditions": WMO.get(d["weather_code"][i], "Mixed"),
            })
        return {"location": f"{loc['name']}, {loc.get('country', '')}".strip(", "),
                "latitude": loc["latitude"], "longitude": loc["longitude"],
                "kind": kind, "days": days}
    except Exception as e:  # tools never crash the conversation
        return {"error": f"Weather unavailable ({type(e).__name__})."}


def get_exchange_rate(base, target, amount=None):
    base, target = (base or "").upper().strip(), (target or "").upper().strip()
    if not (re.fullmatch(r"[A-Z]{3}", base) and re.fullmatch(r"[A-Z]{3}", target)):
        return {"error": "Use 3-letter ISO currency codes such as EUR or JPY."}
    try:
        r = requests.get("https://api.frankfurter.app/latest",
                         params={"from": base, "to": target}, timeout=TIMEOUT)
        rate = r.json().get("rates", {}).get(target) if r.status_code == 200 else None
        if rate is None:
            return {"error": f"No rate for {base}->{target}; only ~30 major currencies are covered."}
        out = {"base": base, "target": target, "rate": rate, "date": r.json().get("date")}
        if amount:
            out["converted_amount"] = round(float(amount) * rate, 2)
        return out
    except Exception as e:
        return {"error": f"Exchange rates unavailable ({type(e).__name__})."}
