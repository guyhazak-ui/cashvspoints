"""
travel_tools.py

Helper functions for two travel-search APIs:

1. SerpApi's Google Flights engine (https://serpapi.com/google-flights-api)
   - Cash-price flight search.

2. Seats.aero (https://seats.aero/api/docs)
   - Award / points flight availability search.

Setup:
    Set these two environment variables (via .env locally, or via your
    hosting provider's dashboard in production):
        SERPAPI_KEY
        SEATS_AERO_API_KEY
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
SEATS_AERO_API_KEY = os.getenv("SEATS_AERO_API_KEY")

SERPAPI_BASE_URL = "https://serpapi.com/search.json"
SEATS_AERO_BASE_URL = "https://seats.aero/partnerapi"

REQUEST_TIMEOUT = 25


class MissingAPIKeyError(Exception):
    """Raised when a required API key is missing or still a placeholder."""


def _check_key(key_value, key_name):
    if not key_value or "paste-your" in key_value:
        raise MissingAPIKeyError(
            f"{key_name} is missing. Set it in your .env file (local) or "
            f"in your hosting provider's environment variables (production)."
        )


def search_flights_serpapi(departure_id, arrival_id, outbound_date, return_date=None,
                            currency="USD", travel_class=None, adults=1):
    """
    Search cash flight prices using SerpApi's Google Flights engine.

    travel_class: one of "economy", "premium_economy", "business", "first".
        Mapped to SerpApi's numeric travel_class codes.
    """
    _check_key(SERPAPI_KEY, "SERPAPI_KEY")

    params = {
        "engine": "google_flights",
        "departure_id": departure_id,
        "arrival_id": arrival_id,
        "outbound_date": outbound_date,
        "currency": currency,
        "hl": "en",
        "adults": adults,
        "api_key": SERPAPI_KEY,
    }

    class_map = {
        "economy": 1,
        "premium_economy": 2,
        "premium": 2,
        "business": 3,
        "first": 4,
    }
    if travel_class and travel_class.lower().replace(" ", "_") in class_map:
        params["travel_class"] = class_map[travel_class.lower().replace(" ", "_")]

    if return_date:
        params["return_date"] = return_date
        params["type"] = "1"
    else:
        params["type"] = "2"

    response = requests.get(SERPAPI_BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def search_award_availability(origin_airport, destination_airport, start_date, end_date, cabin=None):
    """
    Search points/miles award availability using the Seats.aero API.

    cabin: one of "economy", "premium", "business", "first". Leave as None
        to return all cabins.
    """
    _check_key(SEATS_AERO_API_KEY, "SEATS_AERO_API_KEY")

    headers = {"Partner-Authorization": SEATS_AERO_API_KEY}

    params = {
        "origin_airport": origin_airport,
        "destination_airport": destination_airport,
        "start_date": start_date,
        "end_date": end_date,
    }
    if cabin:
        params["cabin"] = cabin

    url = f"{SEATS_AERO_BASE_URL}/search"
    response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()
