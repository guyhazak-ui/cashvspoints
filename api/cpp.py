"""
cpp.py

Cents-Per-Point (CPP) calculation and verdict-icon logic shared by both
the structured search and AI-agent modes.

CPP Yield = (cash_price - taxes_fees) / points_cost * 100
    -> the cents of value you get per point/mile redeemed, versus paying cash.

Verdict icons (matches the CLAUDE.md flight-search response format):
    🟢  Best Points Value  (top award redemption overall, by CPP yield)
    💵  Cheapest Cash Deal (lowest total cash price overall)
    ⚠️  High fees          (taxes/fees disproportionate to price)
    ❌  Poor redemption    (CPP yield below a reasonable threshold)
"""

POOR_REDEMPTION_THRESHOLD_CPP = 1.0   # cents per point
HIGH_FEES_ABSOLUTE_USD = 200          # flag if taxes/fees alone exceed this
HIGH_FEES_RATIO = 0.35                # or if fees are >35% of the equivalent cash price


def compute_cpp(cash_price, taxes_fees, points_cost):
    """
    Returns CPP yield (float, cents per point) or None if points_cost is 0/None
    or cash_price is unavailable.
    """
    if not points_cost or points_cost <= 0:
        return None
    if cash_price is None:
        return None
    net_value = cash_price - (taxes_fees or 0)
    if net_value <= 0:
        return 0.0
    return round((net_value / points_cost) * 100, 2)


def is_high_fees(taxes_fees, cash_price):
    if taxes_fees is None:
        return False
    if taxes_fees >= HIGH_FEES_ABSOLUTE_USD:
        return True
    if cash_price and cash_price > 0 and (taxes_fees / cash_price) >= HIGH_FEES_RATIO:
        return True
    return False


def is_poor_redemption(cpp_yield):
    return cpp_yield is not None and cpp_yield < POOR_REDEMPTION_THRESHOLD_CPP


def assign_verdicts(options):
    """
    Given a flat list of option dicts (each possibly with 'cash_price',
    'taxes_fees', 'points_cost', 'cpp_yield'), attach a 'verdict_icons' list
    to each option per the CLAUDE.md rules. Mutates and returns the list.

    Exactly one option (if any award options exist) gets 🟢 Best Points Value
    (highest cpp_yield). Exactly one option (if any cash options exist) gets
    💵 Cheapest Cash Deal (lowest cash_price among cash-payable options).
    ⚠️ and ❌ can apply to any number of rows independently.
    """
    if not options:
        return options

    award_options = [o for o in options if o.get("points_cost")]
    cash_options = [o for o in options if o.get("cash_price") is not None]

    best_points_id = None
    if award_options:
        best = max(award_options, key=lambda o: (o.get("cpp_yield") or -1))
        best_points_id = id(best)

    cheapest_cash_id = None
    if cash_options:
        cheapest = min(cash_options, key=lambda o: o["cash_price"])
        cheapest_cash_id = id(cheapest)

    for o in options:
        icons = []
        if id(o) == best_points_id:
            icons.append("🟢")
        if id(o) == cheapest_cash_id:
            icons.append("💵")
        if is_high_fees(o.get("taxes_fees"), o.get("cash_price")):
            icons.append("⚠️")
        if is_poor_redemption(o.get("cpp_yield")):
            icons.append("❌")
        o["verdict_icons"] = icons

    return options
