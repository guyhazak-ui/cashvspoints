"""
ai_parser.py

Turns a free-text query like:
    "I want to fly from JFK to LAX next weekend in business class using
     Chase points or cash, what's my best option?"
into a structured search request:
    {
        "origin": "JFK", "destination": "LAX",
        "depart_date": "2026-08-01", "return_date": "2026-08-03",
        "cabin": "business", "passengers": 1,
        "payment_pref": "both",   # "cash" | "points" | "both"
        "notes": "..."
    }

Two parsing strategies:
1. If ANTHROPIC_API_KEY is set, use Claude to parse the query into JSON
   (much more robust -- handles arbitrary phrasing, typos, relative dates).
2. Otherwise, fall back to a lightweight rule-based parser (regex + keyword
   matching + relative-date heuristics) so the app works with zero LLM
   dependency out of the box.
"""

import os
import re
import json
from datetime import date, timedelta

from airports import resolve_airport

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

CABIN_KEYWORDS = [
    ("first class", "first"),
    ("first", "first"),
    ("business class", "business"),
    ("business", "business"),
    ("premium economy", "premium_economy"),
    ("premium", "premium_economy"),
    ("economy", "economy"),
]

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _next_weekday(from_date, weekday_index):
    days_ahead = weekday_index - from_date.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return from_date + timedelta(days=days_ahead)


def _extract_cabin(text_lower):
    for phrase, code in CABIN_KEYWORDS:
        if phrase in text_lower:
            return code
    return "economy"


def _extract_payment_pref(text_lower):
    mentions_points = any(w in text_lower for w in ["point", "points", "mile", "miles", "award"])
    mentions_cash = any(w in text_lower for w in ["cash", "pay", "dollar", "$", "price"])
    if mentions_points and mentions_cash:
        return "both"
    if mentions_points:
        return "points"
    if mentions_cash:
        return "cash"
    return "both"


def _extract_passengers(text_lower):
    m = re.search(r"(\d+)\s*(passenger|passengers|people|adults|travelers|traveller)", text_lower)
    if m:
        return max(1, int(m.group(1)))
    return 1


def _extract_dates(text_lower, today=None):
    """Best-effort relative/absolute date extraction. Returns (depart, return)
    as 'YYYY-MM-DD' strings. Defaults to a 3-day trip starting in 2 weeks
    if nothing recognizable is found."""
    today = today or date.today()

    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text_lower)
    if m:
        depart = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return depart.isoformat(), (depart + timedelta(days=3)).isoformat()

    months = ["january", "february", "march", "april", "may", "june", "july",
              "august", "september", "october", "november", "december"]
    month_abbrevs = {
        "jan": "january", "feb": "february", "mar": "march", "apr": "april",
        "may": "may", "jun": "june", "jul": "july", "aug": "august",
        "sep": "september", "sept": "september", "oct": "october",
        "nov": "november", "dec": "december",
    }

    def _month_index(name):
        full = month_abbrevs.get(name, name)
        return months.index(full) + 1

    def _resolve_year(month_index):
        return today.year if month_index >= today.month else today.year + 1

    # Explicit "Month Day (to Month Day)" mentions, e.g. "January 5 to
    # January 10" or "Jan 5th - Jan 10th". Handles both same-month and
    # cross-month ranges, abbreviated or full month names, and falls back to
    # a default trip length if only one date is mentioned.
    month_pattern = "|".join(months + list(month_abbrevs.keys()))
    date_matches = list(re.finditer(
        rf"\b({month_pattern})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", text_lower
    ))
    if date_matches:
        first_mo, first_day = date_matches[0].group(1), int(date_matches[0].group(2))
        first_month_idx = _month_index(first_mo)
        depart = date(_resolve_year(first_month_idx), first_month_idx, first_day)

        if len(date_matches) >= 2:
            second_mo, second_day = date_matches[1].group(1), int(date_matches[1].group(2))
            second_month_idx = _month_index(second_mo)
            return_year = depart.year if second_month_idx >= first_month_idx else depart.year + 1
            ret = date(return_year, second_month_idx, second_day)
            if ret <= depart:
                ret = depart + timedelta(days=5)
            return depart.isoformat(), ret.isoformat()

        return depart.isoformat(), (depart + timedelta(days=5)).isoformat()

    if "next weekend" in text_lower:
        sat = _next_weekday(today, 5)
        return sat.isoformat(), (sat + timedelta(days=2)).isoformat()

    if "this weekend" in text_lower:
        sat = _next_weekday(today, 5) if today.weekday() < 5 else today
        return sat.isoformat(), (sat + timedelta(days=2)).isoformat()

    for i, wd in enumerate(WEEKDAYS):
        if f"next {wd}" in text_lower:
            d = _next_weekday(today, i)
            return d.isoformat(), (d + timedelta(days=5)).isoformat()

    if "tomorrow" in text_lower:
        d = today + timedelta(days=1)
        return d.isoformat(), (d + timedelta(days=3)).isoformat()

    for i, mo in enumerate(months, start=1):
        if mo in text_lower:
            year = today.year if i > today.month or (i == today.month) else today.year + 1
            if i < today.month:
                year = today.year + 1
            d = date(year, i, 14)
            return d.isoformat(), (d + timedelta(days=5)).isoformat()

    default_depart = today + timedelta(days=14)
    return default_depart.isoformat(), (default_depart + timedelta(days=3)).isoformat()


FILLER_PHRASES = ["round trip", "round-trip", "roundtrip", "one way", "one-way", "oneway"]


def _rule_based_parse(text):
    text_lower = text.lower()
    route_search_text = text_lower
    for phrase in FILLER_PHRASES:
        route_search_text = route_search_text.replace(phrase, " ")

    origin, destination = None, None
    month_names = "|".join([
        "january", "february", "march", "april", "may", "june", "july",
        "august", "september", "october", "november", "december",
        "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    ])
    base_stopwords = rf"next|this|on|in|for|using|with|departing|tomorrow|{month_names}"
    stop_lookahead = rf"(?:\s+(?:{base_stopwords})|[,.\?!]|$)"
    # "from" is only safe as a stop-word once we already know we're inside an
    # explicit "to DEST from ORIGIN" match -- it lets us stop at a trailing
    # date range like "...from London from January 5 to January 10" without
    # swallowing it into the origin. Adding it to the generic fallback
    # pattern below would cause false matches on phrases like "want to fly
    # from JFK to LAX" (matching "i want"/"fly" before reaching "from jfk").
    stop_lookahead_with_from = rf"(?:\s+(?:{base_stopwords}|from|starting|between)|[,.\?!]|$)"

    # Try explicit keyword orders first -- unambiguous because both "to" and
    # "from" are present. Try "from ORIGIN to DEST" before the reordered
    # "to DEST from ORIGIN", since the former is far more common phrasing.
    m_from_to = re.search(
        r"\bfrom\s+([a-zA-Z]+(?:\s[a-zA-Z]+)?)\s+to\s+([a-zA-Z]+(?:\s[a-zA-Z]+)?)" + stop_lookahead,
        route_search_text,
    )
    m_to_from = re.search(
        r"\bto\s+([a-zA-Z]+(?:\s[a-zA-Z]+)?)\s+from\s+([a-zA-Z]+(?:\s[a-zA-Z]+)?)" + stop_lookahead_with_from,
        route_search_text,
    )

    if m_from_to:
        origin = resolve_airport(m_from_to.group(1))
        destination = resolve_airport(m_from_to.group(2))
    elif m_to_from:
        destination = resolve_airport(m_to_from.group(1))
        origin = resolve_airport(m_to_from.group(2))
    else:
        # Fall back to a bare "ORIGIN to DEST" order with no "from" keyword.
        m = re.search(
            r"([a-zA-Z]+(?:\s[a-zA-Z]+)?)\s+to\s+([a-zA-Z]+(?:\s[a-zA-Z]+)?)" + stop_lookahead,
            route_search_text,
        )
        if m:
            origin = resolve_airport(m.group(1))
            destination = resolve_airport(m.group(2))

    if not (origin and destination):
        codes = re.findall(r"\b([A-Z]{3})\b", text)
        if len(codes) >= 2:
            origin, destination = codes[0], codes[1]

    depart_date, return_date = _extract_dates(text_lower)
    cabin = _extract_cabin(text_lower)
    payment_pref = _extract_payment_pref(text_lower)
    passengers = _extract_passengers(text_lower)

    return {
        "origin": origin,
        "destination": destination,
        "depart_date": depart_date,
        "return_date": return_date,
        "cabin": cabin,
        "passengers": passengers,
        "payment_pref": payment_pref,
        "parse_method": "rule_based",
    }


def _anthropic_parse(text):
    """Uses Claude to parse the query into strict JSON. Falls back to the
    rule-based parser on any error (missing package, API error, bad JSON)."""
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        today_str = date.today().isoformat()
        prompt = (
            "Extract a structured flight search from this user query. "
            "Respond with ONLY a JSON object, no other text, with keys: "
            "origin (3-letter IATA code), destination (3-letter IATA code), "
            "depart_date (YYYY-MM-DD), return_date (YYYY-MM-DD or null for one-way), "
            "cabin (one of: economy, premium_economy, business, first), "
            "passengers (integer), payment_pref (one of: cash, points, both). "
            f"Today's date is {today_str}. Resolve relative dates (e.g. 'next weekend') "
            f"relative to today. Resolve city names to their primary airport IATA code.\n\n"
            f"Query: {text}"
        )
        resp = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        parsed["parse_method"] = "anthropic"
        parsed.setdefault("passengers", 1)
        return parsed
    except Exception:
        return None


def parse_query(text):
    """Main entry point. Tries Anthropic parsing if a key is configured,
    otherwise (or on failure) falls back to the rule-based parser."""
    if ANTHROPIC_API_KEY:
        result = _anthropic_parse(text)
        if result and result.get("origin") and result.get("destination"):
            return result
    return _rule_based_parse(text)
