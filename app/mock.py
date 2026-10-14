"""Offline stand-in for the OpenAI client (ATLAS_MOCK=1). Lets you run and test the UI
without an API key. Mimics just the fields the app reads."""
import base64
import json
import struct
import zlib
from datetime import date, timedelta
from types import SimpleNamespace as NS


def _usage(i, o):
    return NS(input_tokens=i, output_tokens=o,
              input_tokens_details=NS(cached_tokens=0, cache_write_tokens=0),
              output_tokens_details=NS(reasoning_tokens=0))


def _msg(text, i=900, o=60):
    return NS(output=[NS(type="message")], output_text=text, usage=_usage(i, o))


SAMPLE_PLAN = {
    "title": "Lanterns, Ramen and Mountain Shrines",
    "destination": "Kyoto, Japan",
    "duration_days": 3,
    "summary": "Three unhurried days pairing Kyoto's great temples with its best small kitchens. "
               "Early starts beat the crowds, afternoons stay gentle, and evenings belong to food.",
    "days": [
        {"day": 1, "theme": "Eastern hills at dawn", "area": "Higashiyama", "activities": [
            {"time_of_day": "morning", "name": "Kiyomizu-dera", "description": "Arrive at opening to have the wooden stage almost to yourselves.", "est_cost": 8},
            {"time_of_day": "afternoon", "name": "Sannenzaka and Ninenzaka", "description": "Wander the stone lanes down to Yasaka Shrine, stopping for matcha.", "est_cost": 15},
            {"time_of_day": "evening", "name": "Gion and Pontocho", "description": "Dinner at a small kappo counter along the river alley.", "est_cost": 90}]},
        {"day": 2, "theme": "Gates and forest trails", "area": "Fushimi and Inari", "activities": [
            {"time_of_day": "morning", "name": "Fushimi Inari summit hike", "description": "Climb through the torii to the summit, about 2-3 hours round trip.", "est_cost": 0},
            {"time_of_day": "afternoon", "name": "Fushimi sake district", "description": "Tasting at the Gekkeikan museum and a canal-side stroll.", "est_cost": 12},
            {"time_of_day": "evening", "name": "Ramen in Ichijoji", "description": "Kyoto's ramen street: rich chicken paitan worth the queue.", "est_cost": 25}]},
        {"day": 3, "theme": "Bamboo and moss", "area": "Arashiyama", "activities": [
            {"time_of_day": "morning", "name": "Arashiyama bamboo grove", "description": "Go before 8:00, then Tenryu-ji's garden as it opens.", "est_cost": 10},
            {"time_of_day": "afternoon", "name": "Okochi Sanso villa", "description": "Hillside garden with tea and a view back over the city.", "est_cost": 12},
            {"time_of_day": "evening", "name": "Nishiki Market and Teramachi", "description": "Graze through the market, then a farewell izakaya.", "est_cost": 60}]},
    ],
    "tips": ["Buy an ICOCA card for buses and trains; buses are slow at peak hours, so use the subway where you can.",
             "Many small restaurants are cash only: carry about 10,000 yen.",
             "Temples open early; arriving at opening time halves the crowds.",
             "Book popular kappo counters a few days ahead."],
    "budget": {"currency": "EUR", "basis": "total for 2 adults", "items": [
        {"category": "Accommodation", "amount": 480, "note": "3 nights, mid-range ryokan-style hotel"},
        {"category": "Food", "amount": 360, "note": "Mix of counters, ramen and markets"},
        {"category": "Local transport", "amount": 45, "note": "ICOCA top-ups"},
        {"category": "Activities", "amount": 70, "note": "Temple and garden entries"},
        {"category": "Other", "amount": 60, "note": "Tea, snacks, souvenirs"}],
        "total": 1015},
    "image_prompt": "Lantern-lit stone lane winding up toward a wooden temple at dusk, autumn maples, distant hills.",
}


def _png(w=96, h=64):
    rows = b""
    for y in range(h):
        rows += b"\x00" + b"".join(bytes((40 + y * 2, 90 + x, 120 + y)) for x in range(w))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def mock_weather(city, start_date, end_date):
    start = date.fromisoformat(start_date)
    n = (date.fromisoformat(end_date) - start).days + 1
    conds = ["Partly cloudy", "Light rain", "Clear", "Overcast", "Clear"]
    return {"location": city, "kind": "forecast", "days": [
        {"date": (start + timedelta(days=i)).isoformat(), "high_c": 21 - i, "low_c": 13 - i,
         "rain_chance_pct": [20, 70, 5, 30, 10][i % 5], "rain_mm": None, "conditions": conds[i % 5]}
        for i in range(n)]}


class _Responses:
    def create(self, model, input, tools=None, text=None, **kw):
        if text:                                           # planner (structured output)
            return _msg(json.dumps(SAMPLE_PLAN), 1800, 2400)
        if not tools:                                      # summariser
            return _msg("- Destination: Kyoto\n- 3 days, food and temples")
        last = input[-1]
        if isinstance(last, dict) and last.get("type") == "function_call_output":
            return _msg("Here's your Kyoto plan. The Fushimi Inari hike on day 2 is the highlight; "
                        "want me to change anything?")
        users = [m for m in input if isinstance(m, dict) and m.get("role") == "user"]
        if len(users) < 2:
            return _msg("Kyoto is a great pick. How many days do you have, and what do you love most "
                        "when you travel: food, temples, hiking, nightlife?")
        args = {"destination": "Kyoto, Japan", "duration_days": 3, "interests": ["food", "temples", "hiking"],
                "start_date": (date.today() + timedelta(days=12)).isoformat(), "travelers": "2 adults",
                "budget_level": "mid-range", "pace": "relaxed", "constraints": None, "currency": "EUR",
                "revision_notes": None}
        call = NS(type="function_call", call_id="call_1", name="create_itinerary", arguments=json.dumps(args))
        return NS(output=[call], output_text="", usage=_usage(1200, 150))


class _Images:
    def generate(self, **kw):
        return NS(data=[NS(b64_json=base64.b64encode(_png()).decode())],
                  usage=NS(input_tokens=60, output_tokens=1500))


class _Moderations:
    def create(self, **kw):
        return NS(results=[NS(flagged="FLAGME" in str(kw.get("input")))])


class MockClient:
    responses = _Responses()
    images = _Images()
    moderations = _Moderations()
