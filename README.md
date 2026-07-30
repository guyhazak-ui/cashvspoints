# Cash vs Points

A dark-mode flight search app for frequent flyers: compare cash prices
against points/miles redemptions side by side, with an automatic
cents-per-point (CPP) yield calculation on every award option.

## Project structure

```
cash-vs-points/
├── api/
│   ├── index.py        FastAPI app -- all backend routes (serverless entry point)
│   ├── travel_tools.py  SerpApi (cash) + Seats.aero (award) client functions
│   ├── cpp.py           CPP-yield math + 🟢/💵/⚠️/❌ verdict logic
│   ├── airports.py      City name -> IATA airport code lookup
│   └── ai_parser.py     Natural-language query parser (rule-based, or Claude if configured)
├── index.html           Dual-mode homepage (AI chat + structured search)
├── styles.css           Dark-mode design system
├── app.js               Frontend logic, results rendering
├── vercel.json          Rewrites /api/* to the Python function; everything else served
│                        directly from the repo root as static files (Vercel zero-config)
├── requirements.txt     Production dependencies (what Vercel installs)
├── requirements-dev.txt Adds uvicorn for local development
└── .env.example          Copy to .env and fill in your keys for local dev
```

Note: `index.html`/`styles.css`/`app.js` live at the repo root, not in a
`public/` folder. Vercel's zero-config static hosting serves any file not
matched by a rewrite directly from wherever it sits in the repo -- keeping
them at the root avoids the need for extra build/output-directory config
(an earlier version of this project used a `public/` folder with an
explicit `builds`/`routes` config, which caused 404s on some Vercel
projects; this simpler layout is the currently-recommended pattern).

## How it works

**Mode A -- AI Travel Agent.** Type a plain-English request like *"fly from
JFK to LAX next weekend in business class using Chase points or cash"*.
`ai_parser.py` extracts origin, destination, dates, cabin, and payment
preference. If you set `ANTHROPIC_API_KEY`, it uses Claude for robust
parsing; otherwise it falls back to a built-in rule-based parser (regex +
keyword + relative-date heuristics), so the app works with zero LLM
dependency.

**Mode B -- Search Engine.** A plain structured form (origin, destination,
dates, passengers). Both modes call the same backend search logic and
render identical results.

**Backend search.** For each of the 4 cabins (Economy, Premium Economy,
Business, First), the backend calls `search_flights_serpapi()` for cash
prices and `search_award_availability()` for points availability, computes
CPP yield per award option, and tags each row with verdict icons (🟢 best
points value, 💵 cheapest cash, ⚠️ high fees, ❌ poor redemption).

## Local development

```bash
cd cash-vs-points
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # then paste in your real SERPAPI_KEY / SEATS_AERO_API_KEY
uvicorn api.index:app --reload --port 8000
```

Then open **http://localhost:8000** in your browser -- `api/index.py` mounts
the frontend files directly when run this way, so one command serves both
the UI and the API on the same origin. (This local-only static mount is
skipped automatically on Vercel, where the repo-root files are served
without going through the Python function at all.)

## Deploying to Vercel

1. Push this folder to a Git repo (GitHub/GitLab/Bitbucket) -- make sure
   `vercel.json`, `index.html`, and `api/` all end up at the repo root, not
   nested inside another folder. Then import the repo at vercel.com, or run
   `vercel` directly from inside `cash-vs-points/` with the Vercel CLI.
2. In the Vercel project's **Settings -> Environment Variables**, add:
   - `SERPAPI_KEY`
   - `SEATS_AERO_API_KEY`
   - `ANTHROPIC_API_KEY` (optional, enables smarter NL parsing)
3. Deploy. `vercel.json`'s single rewrite sends `/api/*` to the Python
   function; everything else (the homepage, `styles.css`, `app.js`) is
   served directly from the repo root with no extra config, so there
   should be no 404s.
4. Sanity-check `GET /api/health` after deploying -- it reports which API
   keys are actually configured, which is the #1 cause of "search failed"
   issues. If you still get a 404 on the homepage, double-check the
   project's **Root Directory** setting in Vercel matches where
   `vercel.json` actually lives in your repo.

## Known limitations / things to verify with real traffic

- **API response parsing is best-effort.** The exact live JSON shapes
  returned by SerpApi's Google Flights engine and by Seats.aero's
  `/partnerapi/search` endpoint could not be verified against a real
  network call while this project was built (outbound requests to those
  domains were blocked in the build environment). `_parse_serpapi_cash()`
  and `_parse_seats_aero_award()` in `api/index.py` handle the documented/
  typical response shapes defensively (they skip malformed entries instead
  of crashing), but you should run one real query per source, inspect the
  raw JSON, and tighten the field-name matching if anything comes back empty.
- **CPP comparison basis.** When an award option's cabin doesn't have a
  matching cash fare from the same search, CPP yield falls back to the
  cheapest cash price found in that same cabin bucket, as a reasonable
  proxy. If SerpApi returns no cash options for a cabin, CPP yield will
  show as unavailable for that cabin's award rows.
- **Loyalty transfer-partner mapping** (`PROGRAM_TRANSFER_MAP` in
  `api/index.py`) covers common programs only -- extend it as you see real
  carrier/program names come back from Seats.aero.
- **Rate limits.** Each search fires up to 8 upstream API calls (4 cabins x
  2 sources). Watch your SerpApi/Seats.aero plan limits if usage grows.
