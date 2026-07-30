"""
api/index.py

FastAPI backend for "Cash vs Points".

Exposes:
    GET  /api/health
    POST /api/search      -- structured search (Mode B)
    POST /api/ai-query     -- natural-language search (Mode A)

Serves as the Vercel serverless entry point for all /api/* requests (see
/vercel.json's rewrite rule). Vercel's zero-config Python runtime
auto-detects any .py file under /api and the `app` ASGI callable below,
wrapping it automatically -- no builds/routes config needed. The static
frontend (index.html/styles.css/app.js at the repo root) is served
directly by Vercel with no function involved.
"""

import sys
import os
import re
import traceback

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

import travel_tools
from cpp import compute_cpp, assign_verdicts
from ai_parser import parse_query

CABINS = ["economy", "premium_economy", "business", "first"]
CABIN_LABELS = {
    "economy": "Economy",
    "premium_economy": "Premium Economy",
    "business": "Business",
    "first": "First Class",
}

# Loyalty-program transfer partners, best-effort mapping for common
# frequent-flyer programs. Keys match Seats.aero's "Source" field, which is
# lowercase with no spaces (confirmed against real API responses, e.g.
# "virginatlantic" not "virgin atlantic"). Extend as needed.
PROGRAM_TRANSFER_MAP = {
    "united": "Chase UR (1:1)",
    "aeroplan": "Amex MR, Chase UR, Citi TYP, Cap1 (1:1)",
    "aircanada": "Amex MR, Chase UR, Citi TYP, Cap1 (1:1)",
    "virginatlantic": "Amex MR, Chase UR, Citi TYP, Cap1, Bilt (1:1)",
    "alaska": "Marriott Bonvoy (3:1)",
    "american": "none (earn direct only)",
    "delta": "Amex MR (1:1)",
    "emirates": "Amex MR, Citi TYP, Cap1 (1:1)",
    "lifemiles": "Amex MR, Citi TYP, Cap1, Bilt (1:1)",
    "ana": "Amex MR (1:1)",
    "singaporeairlines": "Amex MR, Chase UR, Citi TYP, Cap1 (1:1)",
    "turkish": "Amex MR, Chase UR, Citi TYP, Cap1, Bilt (1:1)",
    "qatar": "Amex MR, Chase UR, Citi TYP, Cap1 (1:1)",
    "flyingblue": "Amex MR, Chase UR, Citi TYP, Cap1, Bilt (1:1)",
    "qantas": "Amex MR, Citi TYP, Cap1 (1:1)",
    "british": "Amex MR, Chase UR, Citi TYP, Cap1, Bilt (1:1)",
    "jetblue": "none (earn direct only)",
    "smiles": "none (earn direct only)",
    "finnair": "Amex MR (1:1)",
    "etihad": "Amex MR, Citi TYP, Cap1 (1:1)",
    "velocity": "Amex MR, Citi TYP, Cap1, Bilt (1:1)",
    "saudia": "—",
}

# Friendlier display names for the same programs, shown in the "Flight
# Details & Airline" column since Seats.aero's cached-availability API
# doesn't return per-flight airline names/numbers -- only which loyalty
# program's award chart this pricing comes from, and which operating
# airline codes fly the route.
PROGRAM_DISPLAY_NAMES = {
    "united": "United MileagePlus",
    "aeroplan": "Air Canada Aeroplan",
    "aircanada": "Air Canada Aeroplan",
    "virginatlantic": "Virgin Atlantic Flying Club",
    "alaska": "Alaska Mileage Plan",
    "american": "American AAdvantage",
    "delta": "Delta SkyMiles",
    "emirates": "Emirates Skywards",
    "lifemiles": "Avianca LifeMiles",
    "ana": "ANA Mileage Club",
    "singaporeairlines": "Singapore KrisFlyer",
    "turkish": "Turkish Miles&Smiles",
    "qatar": "Qatar Privilege Club",
    "flyingblue": "Air France/KLM Flying Blue",
    "qantas": "Qantas Frequent Flyer",
    "british": "British Airways Executive Club",
    "jetblue": "JetBlue TrueBlue",
    "smiles": "Smiles (GOL)",
    "finnair": "Finnair Plus",
    "etihad": "Etihad Guest",
    "velocity": "Virgin Australia Velocity",
    "saudia": "Saudia Alfursan",
}

# Seats.aero's cabin field prefixes: Y=Economy, W=Premium Economy,
# J=Business, F=First -- standard IATA booking-class letters.
CABIN_LETTER = {"economy": "Y", "premium_economy": "W", "business": "J", "first": "F"}

CURRENCY_SYMBOLS = {"USD": "$", "GBP": "£", "EUR": "€", "CAD": "$", "AUD": "$"}

app = FastAPI(title="Cash vs Points API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    origin: str
    destination: str
    depart_date: str
    return_date: Optional[str] = None
    passengers: int = 1


class AIQueryRequest(BaseModel):
    query: str


_SECRET_PARAM_RE = re.compile(
    r"(api_key|Partner-Authorization|authorization)=([^&\s'\"]+)", re.IGNORECASE
)


def _sanitize_error(message):
    """Never let raw upstream error text -- which can embed API keys in the
    request URL -- reach the HTTP response or the browser. Redact any
    key/token-shaped query params before this is added to `warnings`."""
    text = str(message)
    text = _SECRET_PARAM_RE.sub(lambda m: f"{m.group(1)}=***REDACTED***", text)
    return text


# ---------------------------------------------------------------------------
# Response parsing (best-effort / defensive)
#
# NOTE: exact live JSON shapes from SerpApi Google Flights and Seats.aero
# could not be verified against a real network call in the environment this
# was built in (outbound requests to those domains were blocked). The
# parsers below handle the documented/typical shapes and fail soft --
# if a field is missing they skip that entry rather than raising. Once you
# run a real query, inspect the raw JSON and tighten these up if needed.
# ---------------------------------------------------------------------------

def _parse_serpapi_cash(raw, cabin):
    options = []
    if not raw:
        return options
    for bucket_key in ("best_flights", "other_flights"):
        for itinerary in raw.get(bucket_key, []) or []:
            try:
                legs = itinerary.get("flights", [])
                if not legs:
                    continue
                first_leg = legs[0]
                last_leg = legs[-1]
                airline = first_leg.get("airline", "Unknown airline")
                flight_number = first_leg.get("flight_number", "")
                depart_time = first_leg.get("departure_airport", {}).get("time", "")
                arrival_time = last_leg.get("arrival_airport", {}).get("time", "")
                direct = len(legs) == 1
                connection = None if direct else legs[0].get("arrival_airport", {}).get("id")
                price = itinerary.get("price")

                options.append({
                    "airline": airline,
                    "flight_number": flight_number,
                    "depart_time": depart_time,
                    "arrival_time": arrival_time,
                    "direct": direct,
                    "connection_airport": connection,
                    "cash_price": price,
                    "taxes_fees": None,
                    "points_cost": None,
                    "transfer_from": "—",
                    "cabin": cabin,
                    "source": "serpapi",
                })
            except Exception:
                continue
    return options


def _parse_seats_aero_award(raw):
    """
    Parses ONE Seats.aero /partnerapi/search response (covering the whole
    requested date range) into per-cabin lists of award options.

    Confirmed against a real response: each entry in raw['data'] is a
    per-day, per-loyalty-program cached availability record -- NOT a
    specific bookable flight. It has no flight number or departure/arrival
    time; instead it carries separate Economy/Premium/Business/First
    (Y/W/J/F) availability, points cost, and taxes for that route on that
    date, plus which operating airline code(s) fly it and whether a direct
    option exists. "Source" is the loyalty program whose award chart this
    pricing comes from (e.g. "united", "virginatlantic") -- shown via
    PROGRAM_DISPLAY_NAMES / PROGRAM_TRANSFER_MAP.

    Returns: {"economy": [...], "premium_economy": [...], "business": [...],
    "first": [...]}, each entry a dict compatible with cpp.assign_verdicts
    and the frontend's results table.
    """
    results = {cabin: [] for cabin in CABIN_LETTER}
    if not raw:
        return results

    entries = raw.get("data") or []
    for entry in entries:
        try:
            route = entry.get("Route") or {}
            program = (route.get("Source") or entry.get("Source") or "").lower()
            transfer_from = PROGRAM_TRANSFER_MAP.get(program, "—")
            display_name = PROGRAM_DISPLAY_NAMES.get(program, program.title() or "Unknown program")
            entry_date = entry.get("Date", "")
            taxes_currency = entry.get("TaxesCurrency", "USD")
            currency_symbol = CURRENCY_SYMBOLS.get(taxes_currency, taxes_currency + " ")

            for cabin_key, letter in CABIN_LETTER.items():
                if not entry.get(f"{letter}Available"):
                    continue

                is_direct = bool(entry.get(f"{letter}Direct"))
                direct_cost = entry.get(f"{letter}DirectMileageCostRaw") or 0
                if is_direct and direct_cost:
                    points_cost = direct_cost
                    taxes_raw = entry.get(f"{letter}DirectTotalTaxesRaw") or 0
                    airlines = entry.get(f"{letter}DirectAirlines") or entry.get(f"{letter}Airlines") or ""
                    remaining_seats = entry.get(f"{letter}DirectRemainingSeatsRaw")
                else:
                    is_direct = False
                    points_cost = entry.get(f"{letter}MileageCostRaw") or 0
                    taxes_raw = entry.get(f"{letter}TotalTaxesRaw") or 0
                    airlines = entry.get(f"{letter}Airlines") or ""
                    remaining_seats = entry.get(f"{letter}RemainingSeatsRaw")

                if not points_cost or not remaining_seats:
                    continue  # no real bookable availability

                taxes_amount = round(taxes_raw / 100.0, 2)

                results[cabin_key].append({
                    "airline": f"{display_name} ({airlines})" if airlines else display_name,
                    "flight_number": "",
                    "depart_time": entry_date,
                    "arrival_time": "",
                    "direct": is_direct,
                    "connection_airport": None,
                    "cash_price": None,
                    "taxes_fees": taxes_amount,
                    "taxes_currency": taxes_currency,
                    "taxes_display": f"{currency_symbol}{taxes_amount:.0f}",
                    "points_cost": points_cost,
                    "transfer_from": transfer_from,
                    "cabin": cabin_key,
                    "source": "seats.aero",
                    "_program": program,
                })
        except Exception:
            continue
    return results


def _dedupe_award_options(options):
    """Seats.aero returns one record per day in the requested date range, so
    the same loyalty program can appear multiple times (once per date).
    Keep only the cheapest (lowest points_cost) instance per program so the
    table stays readable, and surface which date that instance applies to
    via depart_time (already the date string)."""
    best_by_program = {}
    for o in options:
        key = o.get("_program", o["airline"])
        if key not in best_by_program or o["points_cost"] < best_by_program[key]["points_cost"]:
            best_by_program[key] = o
    return list(best_by_program.values())


def _run_full_search(origin, destination, depart_date, return_date, passengers):
    cabins_out = {cabin: [] for cabin in CABINS}
    warnings = []

    # Cash: one call per cabin -- SerpApi's travel_class param genuinely
    # filters results (confirmed: Economy/Premium/Business/First return
    # distinctly different price sets), so this can't be collapsed to one call.
    cash_by_cabin = {}
    for cabin in CABINS:
        try:
            raw_cash = travel_tools.search_flights_serpapi(
                origin, destination, depart_date, return_date,
                travel_class=cabin, adults=passengers,
            )
            cash_by_cabin[cabin] = _parse_serpapi_cash(raw_cash, cabin)
        except travel_tools.MissingAPIKeyError as e:
            warnings.append(_sanitize_error(f"Cash search ({CABIN_LABELS[cabin]}): {e}"))
        except Exception as e:
            warnings.append(_sanitize_error(f"Cash search ({CABIN_LABELS[cabin]}) failed: {e}"))

    # Award: ONE call covers all 4 cabins at once -- Seats.aero's response
    # includes separate Y/W/J/F (economy/premium/business/first) pricing on
    # every record regardless of the "cabin" query param, so calling it
    # per-cabin (as an earlier version of this code did) was 4x redundant
    # against a metered API plan.
    award_by_cabin = {cabin: [] for cabin in CABINS}
    try:
        raw_award = travel_tools.search_award_availability(
            origin, destination, depart_date, return_date or depart_date,
        )
        award_by_cabin = _parse_seats_aero_award(raw_award)
    except travel_tools.MissingAPIKeyError as e:
        warnings.append(_sanitize_error(f"Award search: {e}"))
    except Exception as e:
        warnings.append(_sanitize_error(f"Award search failed: {e}"))

    for cabin in CABINS:
        cash_options = cash_by_cabin.get(cabin, [])
        award_options = _dedupe_award_options(award_by_cabin.get(cabin, []))

        # Use the cheapest cash price in this cabin as the comparison point
        # for CPP yield (Seats.aero doesn't return its own cash comparison).
        # Note: if taxes are in a non-USD currency (see taxes_currency),
        # this comparison isn't currency-converted -- a known simplification.
        cheapest_cash = min((o["cash_price"] for o in cash_options if o["cash_price"]), default=None)
        for a in award_options:
            a["cpp_yield"] = compute_cpp(cheapest_cash, a.get("taxes_fees"), a.get("points_cost"))

        combined = assign_verdicts(cash_options + award_options)
        if combined:
            cabins_out[cabin] = combined

    all_options = [o for opts in cabins_out.values() for o in opts]
    award_all = [o for o in all_options if o.get("points_cost")]
    cash_all = [o for o in all_options if o.get("cash_price") is not None]

    best_points = max(award_all, key=lambda o: (o.get("cpp_yield") or -1), default=None)
    cheapest_cash_overall = min(cash_all, key=lambda o: o["cash_price"], default=None)

    summary = {
        "best_points_value": best_points,
        "cheapest_cash_deal": cheapest_cash_overall,
    }

    return {
        "summary": summary,
        "cabins": cabins_out,
        "warnings": warnings,
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "serpapi_key_configured": bool(travel_tools.SERPAPI_KEY),
        "seats_aero_key_configured": bool(travel_tools.SEATS_AERO_API_KEY),
        "anthropic_key_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
    }


DEBUG = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")


def _error_response(e):
    """Never leak API keys or internal stack traces to the client. Full
    detail still goes to server logs (stderr) for debugging; the client
    only gets a sanitized message, plus the traceback if DEBUG=true."""
    print(traceback.format_exc(), file=sys.stderr)
    payload = {"error": _sanitize_error(e)}
    if DEBUG:
        payload["trace"] = _sanitize_error(traceback.format_exc())
    return payload


@app.get("/api/debug-award")
def debug_award(origin: str, destination: str, start: str, end: str, cabin: Optional[str] = None):
    """TEMPORARY: returns the raw, unparsed Seats.aero response so the
    exact field names can be verified against live data and
    _parse_seats_aero_award() can be corrected. Gated behind DEBUG=true
    since it proxies arbitrary queries against your metered Seats.aero
    plan -- remove this route (and the DEBUG env var) once the award
    parser is confirmed working against real data."""
    if not DEBUG:
        return {"error": "Debug endpoints are disabled. Set DEBUG=true in environment variables to enable."}
    try:
        raw = travel_tools.search_award_availability(origin, destination, start, end, cabin=cabin)
        return raw
    except Exception as e:
        return _error_response(e)


@app.post("/api/search")
def search(req: SearchRequest):
    try:
        result = _run_full_search(
            req.origin.strip().upper(), req.destination.strip().upper(),
            req.depart_date, req.return_date, req.passengers,
        )
        return result
    except Exception as e:
        return _error_response(e)


@app.post("/api/ai-query")
def ai_query(req: AIQueryRequest):
    try:
        parsed = parse_query(req.query)
        if not parsed.get("origin") or not parsed.get("destination"):
            return {
                "error": "Couldn't recognize one of those airports/cities. Try naming a major "
                         "city (e.g. \"Tel Aviv\") or a 3-letter airport code (e.g. \"TLV\") directly.",
                "parsed_request": parsed,
            }

        result = _run_full_search(
            parsed["origin"], parsed["destination"],
            parsed["depart_date"], parsed.get("return_date"),
            parsed.get("passengers", 1),
        )

        bp = result["summary"]["best_points_value"]
        cc = result["summary"]["cheapest_cash_deal"]
        reply_parts = [
            f"Searched {parsed['origin']} → {parsed['destination']} "
            f"({CABIN_LABELS.get(parsed.get('cabin', 'economy'), 'Economy')}) "
            f"for {parsed['depart_date']}"
            + (f" – {parsed['return_date']}." if parsed.get("return_date") else "."),
        ]
        if bp:
            taxes_text = bp.get("taxes_display") or f"${bp.get('taxes_fees', 0):.0f}"
            reply_parts.append(
                f"Best points value: {bp['airline']} for {bp['points_cost']:,} points "
                f"(+{taxes_text} fees), a {bp['cpp_yield']}¢/point yield."
            )
        if cc:
            reply_parts.append(f"Cheapest cash deal: {cc['airline']} at ${cc['cash_price']:.0f}.")
        if not bp and not cc:
            reply_parts.append("No results came back – check the warnings below.")

        result["parsed_request"] = parsed
        result["assistant_reply"] = " ".join(reply_parts)
        return result
    except Exception as e:
        return _error_response(e)


# ---------------------------------------------------------------------------
# Static frontend fallback.
#
# In production on Vercel, index.html/styles.css/app.js live at the repo
# root and Vercel serves them directly -- this app is never asked for them.
# Locally, though, running just `uvicorn api.index:app` won't have anything
# serving the frontend unless we mount it here too. This mount is registered
# LAST, after all /api/* routes above, so it only catches whatever those
# routes don't handle (i.e. it never shadows /api/search or /api/ai-query).
# ---------------------------------------------------------------------------
_repo_root = os.path.join(os.path.dirname(__file__), "..")
if os.path.isfile(os.path.join(_repo_root, "index.html")):
    app.mount("/", StaticFiles(directory=_repo_root, html=True), name="static")
