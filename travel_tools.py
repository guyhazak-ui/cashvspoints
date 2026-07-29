"""
travel_tools.py

Simple helper functions for two travel-search APIs:

1. SerpApi's Google Flights engine  (https://serpapi.com/google-flights-api)
   - Cash-price flight search.

2. Seats.aero  (https://seats.aero/api/docs)
   - Award / points flight availability search.

Setup:
    1. pip install requests python-dotenv
    2. Put your API keys in the .env file next to this script:
         SERPAPI_KEY="..."
         SEATS_AERO_API_KEY="..."
    3. Run this file directly to try a sample search, or import the
       functions into your own script:
         from travel_tools import search_flights_serpapi, search_award_availability

No coding experience needed to use this — just edit the values in the
`if __name__ == "__main__":` block at the bottom and run:
    python travel_tools.py
"""

import os
import sys
import requests
from dotenv import load_dotenv

# Load keys from the .env file in the same folder as this script
load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
SEATS_AERO_API_KEY = os.getenv("SEATS_AERO_API_KEY")

SERPAPI_BASE_URL = "https://serpapi.com/search.json"
SEATS_AERO_BASE_URL = "https://seats.aero/partnerapi"


def _check_key(key_value, key_name):
    """Raise a clear error if a required API key is missing."""
    if not key_value or "paste-your" in key_value:
        raise ValueError(
            f"{key_name} is missing. Open the .env file and paste your "
            f"real key in place of the placeholder text."
        )


def search_flights_serpapi(departure_id, arrival_id, outbound_date, return_date=None, currency="USD"):
    """
    Search cash flight prices using SerpApi's Google Flights engine.

    Args:
        departure_id (str): Origin airport code, e.g. "JFK"
        arrival_id (str): Destination airport code, e.g. "LAX"
        outbound_date (str): Departure date, format "YYYY-MM-DD"
        return_date (str, optional): Return date, format "YYYY-MM-DD".
            Leave as None for a one-way search.
        currency (str): Currency code for prices. Default "USD".

    Returns:
        dict: Parsed JSON response from SerpApi.
    """
    _check_key(SERPAPI_KEY, "SERPAPI_KEY")

    params = {
        "engine": "google_flights",
        "departure_id": departure_id,
        "arrival_id": arrival_id,
        "outbound_date": outbound_date,
        "currency": currency,
        "hl": "en",
        "api_key": SERPAPI_KEY,
    }

    if return_date:
        params["return_date"] = return_date
        params["type"] = "1"  # round trip
    else:
        params["type"] = "2"  # one way

    response = requests.get(SERPAPI_BASE_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def search_award_availability(origin_airport, destination_airport, start_date, end_date, cabin=None):
    """
    Search points/miles award availability using the Seats.aero API.

    Args:
        origin_airport (str): Origin airport code, e.g. "JFK"
        destination_airport (str): Destination airport code, e.g. "LHR"
        start_date (str): Start of search window, format "YYYY-MM-DD"
        end_date (str): End of search window, format "YYYY-MM-DD"
        cabin (str, optional): One of "economy", "premium", "business",
            "first". Leave as None to return all cabins.

    Returns:
        dict: Parsed JSON response from Seats.aero.
    """
    _check_key(SEATS_AERO_API_KEY, "SEATS_AERO_API_KEY")

    headers = {
        "Partner-Authorization": SEATS_AERO_API_KEY,
    }

    params = {
        "origin_airport": origin_airport,
        "destination_airport": destination_airport,
        "start_date": start_date,
        "end_date": end_date,
    }

    if cabin:
        params["cabin"] = cabin

    url = f"{SEATS_AERO_BASE_URL}/search"
    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    # ------------------------------------------------------------------
    # Edit the values below, then run:   python travel_tools.py
    # ------------------------------------------------------------------

    print("Searching cash flights with SerpApi...")
    try:
        flight_results = search_flights_serpapi(
            departure_id="JFK",
            arrival_id="LAX",
            outbound_date="2026-09-01",
            return_date="2026-09-08",
        )
        print(flight_results)
    except Exception as e:
        print(f"SerpApi search failed: {e}", file=sys.stderr)

    print("\nSearching award availability with Seats.aero...")
    try:
        award_results = search_award_availability(
            origin_airport="JFK",
            destination_airport="LHR",
            start_date="2026-09-01",
            end_date="2026-09-08",
        )
        print(award_results)
    except Exception as e:
        print(f"Seats.aero search failed: {e}", file=sys.stderr)
