"""The travel agent: conversation (cheap model) -> create_itinerary tool -> planner (GPT-6)
-> structured JSON plan -> illustration (GPT Image)."""
import base64
import json
import os
import secrets
import threading
import time
from datetime import date, timedelta

from . import config, prompts, security, tools
from .usage import UsageTracker


def make_client():
    if config.MOCK:
        from .mock import MockClient
        return MockClient()
    from openai import OpenAI
    return OpenAI(max_retries=2, timeout=180)


CLIENT = make_client()


class AgentError(Exception):
    """An error with a message that is safe to show to the user."""


def _estimate_tokens(messages):
    return sum(len(m.get("content") or "") for m in messages) // 4 + 50


def _call(tracker, label, model, **kwargs):
    t0 = time.perf_counter()
    resp = CLIENT.responses.create(model=model, **kwargs)
    searches = sum(1 for item in resp.output if getattr(item, "type", "") == "web_search_call")
    tracker.add_text(label, model, resp.usage, time.perf_counter() - t0,
                     extra_usd=searches * config.WEB_SEARCH_PRICE_PER_CALL)
    return resp


class Session:
    def __init__(self):
        self.id = secrets.token_urlsafe(18)
        self.created = self.last_seen = time.time()
        self.lock = threading.Lock()
        self.usage = UsageTracker()
        self.history = [{"role": "assistant", "content": prompts.GREETING}]
        self.summary = None
        self.brief = None
        self.plans = {}            # plan_id -> plan dict
        self.latest_plan_id = None
        self.images = 0
        self.turns = 0

    # ------------------------------------------------------------------ chat
    def chat(self, text):
        """One user turn. Returns {'reply': str, 'plan_id': str|None}."""
        if self.turns >= config.MAX_TURNS_PER_SESSION:
            raise AgentError("This conversation has reached its length limit. Start a new trip to keep planning.")
        if self.usage.cost_usd >= config.MAX_SESSION_COST_USD:
            raise AgentError("This conversation has reached its spending limit. Start a new trip to keep planning.")
        if security.is_flagged(CLIENT, text):
            return {"reply": "I can't help with that. Where would you like to travel?", "plan_id": None}

        self.turns += 1
        self.history.append({"role": "user", "content": text})
        self._maybe_summarise()

        tools_list = [prompts.CREATE_ITINERARY_TOOL, prompts.WEATHER_TOOL, prompts.FX_TOOL]
        if config.CHAT_WEB_SEARCH:
            tools_list.append({"type": "web_search"})
        instructions = prompts.chat_instructions(
            self.summary,
            json.dumps(self.brief, ensure_ascii=False) if self.brief else None,
            self.plans[self.latest_plan_id]["title"] if self.latest_plan_id else None)

        items = [dict(m) for m in self.history]
        new_plan_id = None
        reply = ""
        for _ in range(6):                      # tool-calling loop with a hard cap
            resp = _call(self.usage, "chat", config.CHAT_MODEL, instructions=instructions,
                         input=items, tools=tools_list, reasoning={"effort": config.CHAT_EFFORT},
                         max_output_tokens=4000)
            calls = [it for it in resp.output if getattr(it, "type", "") == "function_call"]
            if not calls:
                reply = resp.output_text or ""
                break
            items += resp.output                  # keep reasoning + call items together
            for call in calls:
                result, plan_id = self._run_tool(call)
                new_plan_id = plan_id or new_plan_id
                items.append({"type": "function_call_output", "call_id": call.call_id,
                              "output": json.dumps(result, ensure_ascii=False)[:6000]})
        else:
            reply = "I got stuck looking that up. Could you rephrase?"

        if security.leaked(reply):
            reply = "I can't share that. Where would you like to travel?"
        if not reply.strip():
            reply = "Your plan is ready. Want me to change anything?" if new_plan_id else "Could you tell me a bit more?"
        self.history.append({"role": "assistant", "content": reply})
        return {"reply": reply, "plan_id": new_plan_id}

    def _run_tool(self, call):
        try:
            args = json.loads(call.arguments or "{}")
        except json.JSONDecodeError:
            return {"error": "Invalid arguments."}, None
        if call.name == "get_weather":
            return tools.get_weather(**args), None
        if call.name == "get_exchange_rate":
            return tools.get_exchange_rate(**args), None
        if call.name == "create_itinerary":
            return self._create_itinerary(args)
        return {"error": f"Unknown tool {call.name}"}, None

    # -------------------------------------------------------------- planning
    def _create_itinerary(self, brief):
        # Validate in code, not only in the prompt: the model gets the error back and asks the user.
        days = brief.get("duration_days") or 0
        if not 1 <= days <= config.MAX_TRIP_DAYS:
            return {"error": f"Trips must be 1-{config.MAX_TRIP_DAYS} days; ask the user to adjust "
                             "or split it into separate legs."}, None
        if brief.get("start_date"):
            try:
                start = date.fromisoformat(brief["start_date"])
            except ValueError:
                return {"error": "start_date is not a valid date; ask the user to confirm it."}, None
            if start < date.today():
                return {"error": "start_date is in the past; ask the user to confirm the dates."}, None
        if len(self.plans) >= config.MAX_PLANS_PER_SESSION:
            return {"error": "Plan limit for this conversation reached; tell the user to start a new trip."}, None

        context = {}
        weather = None
        if brief.get("start_date"):
            start = date.fromisoformat(brief["start_date"])
            weather_fn = tools.get_weather
            if config.MOCK:
                from .mock import mock_weather as weather_fn
            weather = weather_fn(brief["destination"], start.isoformat(),
                                 (start + timedelta(days=days - 1)).isoformat())
            if "error" not in weather:
                context["weather"] = weather
        if brief.get("revision_notes") and self.latest_plan_id:
            prev = dict(self.plans[self.latest_plan_id])
            prev.pop("weather", None)
            context["previous_plan"] = prev

        plan = self._plan(brief, context)
        if weather and "error" not in weather:
            plan["weather"] = {"kind": weather["kind"], "days": weather["days"][:days]}
        plan_id = secrets.token_urlsafe(8)
        plan["id"] = plan_id
        self.plans[plan_id] = plan
        self.latest_plan_id = plan_id
        self.brief = {k: v for k, v in brief.items() if k != "revision_notes"}
        return {"status": "created and shown to the user", "title": plan["title"],
                "days": [f"Day {d['day']}: {d['theme']}" for d in plan["days"]],
                "budget_total": f"{plan['budget']['total']:,.0f} {plan['budget']['currency']}"}, plan_id

    def _plan(self, brief, context):
        payload = "Trip brief:\n" + json.dumps(brief, ensure_ascii=False, indent=1)
        if context:
            payload += "\n\nContext:\n" + json.dumps(context, ensure_ascii=False)
        kwargs = dict(
            instructions=prompts.PLANNER_INSTRUCTIONS,
            input=[{"role": "user", "content": payload}],
            reasoning={"effort": config.PLANNER_EFFORT},
            text={"format": {"type": "json_schema", "name": "travel_itinerary",
                             "schema": prompts.ITINERARY_SCHEMA, "strict": True}},
            max_output_tokens=24000,
        )
        if config.PLANNER_WEB_SEARCH:
            try:
                resp = _call(self.usage, "planner", config.PLANNER_MODEL,
                             tools=[{"type": "web_search"}], **kwargs)
            except Exception:          # e.g. web search unavailable for this org/model
                resp = _call(self.usage, "planner", config.PLANNER_MODEL, **kwargs)
        else:
            resp = _call(self.usage, "planner", config.PLANNER_MODEL, **kwargs)
        try:
            plan = json.loads(resp.output_text)
        except (json.JSONDecodeError, TypeError):
            raise AgentError("The planner returned an incomplete plan. Ask me to try again.")
        # Trust, but verify: recompute the budget and fix day numbering in code.
        items = plan["budget"]["items"]
        plan["budget"]["total"] = round(sum(float(i["amount"]) for i in items), 2)
        for n, d in enumerate(plan["days"], 1):
            d["day"] = n
        return plan

    # ----------------------------------------------------------------- image
    def illustrate(self, plan_id):
        plan = self.plans.get(plan_id)
        if not plan:
            raise AgentError("That plan no longer exists.")
        if plan.get("image"):
            return plan["image"]
        if self.images >= config.MAX_IMAGES_PER_SESSION:
            raise AgentError("Image limit for this conversation reached.")
        self.images += 1
        prompt = (f"Travel-poster illustration: {plan['image_prompt']} "
                  f"Setting: {plan['destination']}. Painterly, warm natural light, rich colour, "
                  "wide composition with calm sky in the upper third. No text, letters, logos or watermarks.")
        t0 = time.perf_counter()
        kwargs = dict(model=config.IMAGE_MODEL, prompt=prompt, size=config.IMAGE_SIZE,
                      quality=config.IMAGE_QUALITY)
        try:
            result = CLIENT.images.generate(**kwargs)
        except Exception:
            kwargs.pop("size"); kwargs.pop("quality")      # fall back to model defaults
            result = CLIENT.images.generate(**kwargs)
        self.usage.add_image(config.IMAGE_MODEL, getattr(result, "usage", None), time.perf_counter() - t0)
        data = base64.b64decode(result.data[0].b64_json)
        os.makedirs(config.DATA_DIR, exist_ok=True)
        name = secrets.token_urlsafe(12) + ".png"
        with open(os.path.join(config.DATA_DIR, name), "wb") as f:
            f.write(data)
        plan["image"] = f"/api/images/{name}"
        return plan["image"]

    # ---------------------------------------------------------- summarising
    def _maybe_summarise(self):
        if _estimate_tokens(self.history) < config.SUMMARY_TRIGGER_TOKENS:
            return
        keep = config.SUMMARY_KEEP_MESSAGES
        old, recent = self.history[:-keep], self.history[-keep:]
        while recent and recent[0]["role"] != "user":   # start the kept part on a user turn
            old.append(recent.pop(0))
        if not old:
            return
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in old)
        if self.summary:
            transcript = f"Previous summary:\n{self.summary}\n\n{transcript}"
        resp = _call(self.usage, "summary", config.CHAT_MODEL,
                     instructions=prompts.SUMMARY_INSTRUCTIONS,
                     input=[{"role": "user", "content": transcript}],
                     reasoning={"effort": "low"}, max_output_tokens=1500)
        self.summary = resp.output_text
        self.history = recent


def plan_to_markdown(plan):
    cur = plan["budget"]["currency"]
    out = [f"# {plan['title']}", "", f"*{plan['destination']}, {plan['duration_days']} days*", "",
           plan["summary"], "", "## Day by day"]
    for d in plan["days"]:
        out += ["", f"### Day {d['day']}: {d['theme']} ({d['area']})"]
        for a in d["activities"]:
            cost = f" (~{a['est_cost']:,.0f} {cur})" if a["est_cost"] else ""
            out.append(f"- **{a['time_of_day'].title()}:** {a['name']}. {a['description']}{cost}")
    out += ["", "## Practical tips"] + [f"- {t}" for t in plan["tips"]]
    b = plan["budget"]
    out += ["", f"## Estimated budget ({cur}, {b['basis']})", "", "| Category | Amount | Note |",
            "|---|---:|---|"]
    out += [f"| {i['category']} | {i['amount']:,.0f} | {i['note']} |" for i in b["items"]]
    out += [f"| **Total** | **{b['total']:,.0f}** | |", "", "*All prices are estimates.*"]
    return "\n".join(out)
