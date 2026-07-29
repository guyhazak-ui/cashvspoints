# Travel Tools Project

## What this is

A small Python project with one script, `travel_tools.py`, that searches:
- **Cash flight prices** via SerpApi's Google Flights engine
- **Points/miles award availability** via the Seats.aero API

The user (Amit) is not a developer. Keep explanations simple, avoid jargon,
and always show exactly which file and line to edit when changes are needed.

## Files in this project

- `.env` — holds the two API keys (`SERPAPI_KEY`, `SEATS_AERO_API_KEY`). Never
  print the contents of this file or the keys themselves in chat.
- `travel_tools.py` — contains two functions, `search_flights_serpapi()` and
  `search_award_availability()`, plus a runnable example at the bottom.
- `CLAUDE.md` — this file.

## Setup (one-time)

1. Install two packages:
   ```
   pip install requests python-dotenv
   ```
2. Open `.env` and paste real API keys in place of the placeholder text.
3. Run the script to test it:
   ```
   python travel_tools.py
   ```

## Where to get API keys

- SerpApi: https://serpapi.com/manage-api-key (requires a SerpApi account)
- Seats.aero: https://seats.aero/ account settings, under API access
  (Seats.aero API access typically requires a paid Pro plan)

## Conventions for future changes

- Airport codes are 3-letter IATA codes (e.g. "JFK", "LAX").
- Dates are always "YYYY-MM-DD" strings.
- Both search functions raise a clear `ValueError` if a key is still the
  placeholder text, so errors are easy to diagnose.
- If adding new API calls, follow the existing pattern: one function per
  endpoint, a docstring explaining inputs/outputs in plain language, and a
  `_check_key()` guard before making the request.
- Do not hardcode API keys directly in `travel_tools.py` — they must always
  come from `.env` via `load_dotenv()`.

## When helping Amit

- He does not code day-to-day, so prefer editing files directly over asking
  him to write code himself.
- Confirm the `.env` keys are filled in before debugging "search failed"
  errors — that's the most common cause.
- Keep any new terminal commands copy-pasteable and explain what each one
  does in one short sentence.
