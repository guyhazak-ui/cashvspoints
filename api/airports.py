"""
airports.py

Small city-name -> IATA airport code lookup, used so the AI Travel Agent
mode can resolve things like "New York" or "London" into airport codes.
Not exhaustive -- covers common frequent-flyer routes. Falls back to
treating the input as an already-valid 3-letter code if not found.
"""

CITY_TO_IATA = {
    "new york": "JFK",
    "nyc": "JFK",
    "newark": "EWR",
    "los angeles": "LAX",
    "la": "LAX",
    "san francisco": "SFO",
    "chicago": "ORD",
    "boston": "BOS",
    "washington": "IAD",
    "washington dc": "IAD",
    "miami": "MIA",
    "seattle": "SEA",
    "denver": "DEN",
    "dallas": "DFW",
    "houston": "IAH",
    "atlanta": "ATL",
    "las vegas": "LAS",
    "london": "LHR",
    "paris": "CDG",
    "tokyo": "HND",
    "singapore": "SIN",
    "hong kong": "HKG",
    "sydney": "SYD",
    "dubai": "DXB",
    "toronto": "YYZ",
    "vancouver": "YVR",
    "amsterdam": "AMS",
    "frankfurt": "FRA",
    "madrid": "MAD",
    "rome": "FCO",
    "barcelona": "BCN",
    "mexico city": "MEX",
    "sao paulo": "GRU",
    "seoul": "ICN",
    "bangkok": "BKK",
    "istanbul": "IST",
    "doha": "DOH",
}


def resolve_airport(text):
    """
    Resolve free-text location to a 3-letter IATA code.
    Returns the resolved code (uppercase), or the original text uppercased
    if it already looks like an airport code (3 letters) or no match found.
    """
    if not text:
        return None
    cleaned = text.strip().lower()
    if cleaned in CITY_TO_IATA:
        return CITY_TO_IATA[cleaned]
    stripped = cleaned.replace(".", "")
    if len(stripped) == 3 and stripped.isalpha():
        return stripped.upper()
    # partial match, e.g. "flying out of new york city"
    for city, code in CITY_TO_IATA.items():
        if city in cleaned:
            return code
    return text.strip().upper()
