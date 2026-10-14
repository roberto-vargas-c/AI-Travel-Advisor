# Atlas: AI travel advisor

A chat assistant that asks what it needs to know about your trip, then turns it into a visual itinerary poster: an AI illustration of the trip, a weather strip, a day-by-day route, a budget chart and practical tips. You can save the poster as a PNG or download the plan as Markdown.

## How it works

```
Browser chat ──► /api/chat ──► gpt-6-luna (conversation, low effort)
                                 │  tools: get_weather · get_exchange_rate · web_search
                                 │  when the brief is complete ──► create_itinerary(brief)
                                 ▼
                       code checks the brief (length, past dates, plan limit)
                       Open-Meteo weather for the travel dates
                                 ▼
                       gpt-6.1-sol (medium effort, + web search)
                       ──► strict JSON itinerary (budget re-totalled in code)
                                 ▼
Browser renders the poster ──► /api/illustrate ──► gpt-image-2.5-flare ──► hero image
```

What it takes from the notebook bonuses:

| Bonus | In the app |
|---|---|
| Conversation memory | Server-side history per session, resent on every call |
| Token and cost tracking | Each call is priced per model (including cached input and web searches); the running total is shown under the chat box |
| Structured output | A strict JSON Schema itinerary that the UI renders as a graphic |
| Tool calling and web search | Weather (forecast or typical for the dates), exchange rates, web search for events, closures and transport |
| Multi-model workflow | A cheap chat model, a stronger planner called through a tool, and an image model |
| Summarising long chats | Older turns are condensed by the cheap model; the current trip brief is kept separately so no details are lost |
| Image generation | A poster illustration built from a scene the planner writes |
| Security | See below |

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # add your OpenAI key
export $(grep -v '^#' .env | xargs)
uvicorn app.main:app --reload
```

Open http://localhost:8000.

To try it without a key, `ATLAS_MOCK=1 uvicorn app.main:app` uses canned responses. Run the tests with `pytest`; they also use mock mode.

## Deploy

The app is a single Docker container. It runs anywhere that runs containers.

**Render (blueprint included)**
1. Push this folder to a GitHub repo.
2. In Render, choose **New → Blueprint** and select the repo. Render reads `render.yaml`.
3. Paste your `OPENAI_API_KEY` when asked, then deploy. You get an `https://…onrender.com` URL.

**Other platforms** (Railway, Fly.io, Google Cloud Run, Azure Container Apps): build the `Dockerfile`, set `OPENAI_API_KEY`, and expose the port in `$PORT` (default 8000). Health check: `/healthz`.

**Before you share the URL**
- Set `DAILY_BUDGET_USD` to what you're willing to spend per day. The app stops answering once that's reached.
- Set a monthly usage limit in the OpenAI dashboard as a second safety net.
- GPT Image models may need **Organization Verification** in the OpenAI dashboard first.
- Sessions and images are stored in memory and on local disk, so a restart clears them. Keep one instance. To scale out, move `SESSIONS` to Redis and images to object storage.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `CHAT_MODEL` | `gpt-6-luna` | Runs every chat turn, so cheap and fast matters |
| `PLANNER_MODEL` | `gpt-6.1-sol` | Change to `gpt-6-astra` for maximum quality (about 5x the price) |
| `IMAGE_MODEL` | `gpt-image-2.5-flare` | `gpt-image-2.5-sunburst` gives the highest quality; `gpt-image-2` is cheaper |
| `PLANNER_EFFORT` | `medium` | `low` is faster; `high` plans more carefully |
| `IMAGE_QUALITY` / `IMAGE_SIZE` | `medium` / `1536x1024` | |
| `CHAT_WEB_SEARCH`, `PLANNER_WEB_SEARCH` | `1` | Each search costs about $0.01 |
| `DAILY_BUDGET_USD` | `10` | Hard stop for the whole deployment |
| `MAX_SESSION_COST_USD` | `1` | Per conversation |
| `MESSAGES_PER_MINUTE_PER_IP` | `15` | |
| `MAX_TRIP_DAYS` | `21` | |

Prices in `app/config.py` were taken from OpenAI's pricing page in October 2026 and are only used for the cost meter.

**Rough cost per finished trip:** a few cents for chat turns with `gpt-6-luna`, about $0.10–0.25 for the plan with `gpt-6.1-sol` at medium effort, plus the illustration (token-billed; check OpenAI's image pricing calculator).

## Security

- The API key stays on the server. The browser only talks to this app.
- Rate limits per IP, a turn and cost cap per session, and a daily budget cap for the whole deployment protect against runaway spending.
- Every message is checked with OpenAI's moderation endpoint.
- Input is normalised, control characters are stripped, and length is capped.
- Brief rules are enforced in code as well as the prompt: trip length, past dates and plan limits are rejected with an error the model passes back to the user.
- Tools call fixed endpoints only, so the model can't make the server request a URL it chooses (no SSRF). Arguments are validated and results are size-capped.
- The prompt tells the model that tool results and web pages are data, not instructions. A random marker in the system prompt detects prompt leaks, and a reply containing it is replaced.
- Model text is inserted into the page as text, never as HTML. A Content Security Policy only allows scripts from this site and one pinned CDN library.
- Image filenames are random and checked against a strict pattern, so paths can't escape the image folder.

What remains: prompt injection can be reduced but not ruled out, and the plan can still be wrong about opening hours or prices. The poster says so.
