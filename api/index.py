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
# frequent-flyer programs. Extend as needed.
PROGRAM_TRANSFER_MAP = {
    "united": "Chase UR (1:1)",
    "aeroplan": "Amex MR, Chase UR, Citi TYP, Cap1 (1:1)",
    "air canada": "Amex MR, Chase UR, Citi TYP, Cap1 (1:1)",
    "virgin atlantic": "Amex MR, Chase UR, Citi TYP, Cap1, Bilt (1:1)",
    "alaska": "Marriott Bonvoy (3:1)",
    "american": "none (earn direct only)",
    "delta": "Amex MR (1:1)",
    "emirates": "Amex MR, Citi TYP, Cap1 (1:1)",
    "avianca lifemiles": "Amex MR, Citi TYP, Cap1, Bilt (1:1)",
    "ana": "Amex MR (1:1)",
    "singapore airlines krisflyer": "Amex MR, Chase UR, Citi TYP, Cap1 (1:1)",
    "turkish": "Amex MR, Chase UR, Citi TYP, Cap1, Bilt (1:1)",
    "qatar": "Amex MR, Chase UR, Citi TYP, Cap1 (1:1)",
}

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


def _parse_seats_aero_award(raw, cabin):
    options = []
    if not raw:
        return options
    entries = raw.get("data") or raw.get("results") or (raw if isinstance(raw, list) else [])
    for entry in entries or []:
        try:
            program = (entry.get("Source") or entry.get("program") or entry.get("airline") or "").lower()
            transfer_from = PROGRAM_TRANSFER_MAP.get(program, "—")

            options.append({
                "airline": entry.get("Carrier") or entry.get("airline") or program.title() or "Unknown",
                "flight_number": entry.get("FlightNumber") or entry.get("flight_number") or "",
                "depart_time": entry.get("DepartsAt") or entry.get("departure_time") or "",
                "arrival_time": entry.get("ArrivesAt") or entry.get("arrival_time") or "",
                "direct": entry.get("Stops", 0) == 0 if entry.get("Stops") is not None else True,
                "connection_airport": entry.get("ConnectionAirport"),
                "cash_price": None,
                "taxes_fees": entry.get("TotalTaxes") or entry.get("taxes") or 0,
                "points_cost": entry.get("MileageCost") or entry.get("points") or entry.get("Cost"),
                "transfer_from": transfer_from,
                "cabin": cabin,
                "source": "seats.aero",
            })
        except Exception:
            continue
    return options


def _run_full_search(origin, destination, depart_date, return_date, passengers):
    cabins_out = {}
    warnings = []

    for cabin in CABINS:
        cash_options, award_options = [], []

        try:
            raw_cash = travel_tools.search_flights_serpapi(
                origin, destination, depart_date, return_date,
                travel_class=cabin, adults=passengers,
            )
            cash_options = _parse_serpapi_cash(raw_cash, cabin)
        except travel_tools.MissingAPIKeyError as e:
            warnings.append(_sanitize_error(f"Cash search ({CABIN_LABELS[cabin]}): {e}"))
        except Exception as e:
            warnings.append(_sanitize_error(f"Cash search ({CABIN_LABELS[cabin]}) failed: {e}"))

        try:
            raw_award = travel_tools.search_award_availability(
                origin, destination, depart_date, return_date or depart_date, cabin=cabin,
            )
            award_options = _parse_seats_aero_award(raw_award, cabin)
        except travel_tools.MissingAPIKeyError as e:
            warnings.append(_sanitize_error(f"Award search ({CABIN_LABELS[cabin]}): {e}"))
        except Exception as e:
            warnings.append(_sanitize_error(f"Award search ({CABIN_LABELS[cabin]}) failed: {e}"))

        # Use the cheapest cash price in this cabin as the comparison point
        # for CPP yield, if the award API doesn't provide its own cash comp.
        cheapest_cash = min((o["cash_price"] for o in cash_options if o["cash_price"]), default=None)
        for a in award_options:
            comp_cash_price = a.get("cash_price") or cheapest_cash
            a["cpp_yield"] = compute_cpp(comp_cash_price, a.get("taxes_fees"), a.get("points_cost"))

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
                "error": "Could not identify both an origin and destination airport in that query.",
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
            reply_parts.append(
                f"Best points value: {bp['airline']} for {bp['points_cost']:,} points "
                f"(+${bp.get('taxes_fees', 0):.0f} fees), a {bp['cpp_yield']}¢/point yield."
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
