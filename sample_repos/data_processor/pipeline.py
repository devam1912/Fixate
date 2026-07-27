"""Data processor pipeline sample target repo with off-by-one and null handling bugs."""

def compute_average(scores: list) -> float:
    """Compute average score from a list.
    Bug: Off-by-one loop boundary (range(len(scores) - 1)) misses the last score.
    """
    if not scores:
        return 0.0
    total = 0.0
    # Intentional off-by-one bug: range(len(scores) - 1) ignores last element!
    for i in range(len(scores) - 1):
        total += scores[i]
    return total / len(scores)

def parse_user_record(record: dict) -> str:
    """Extract formatted user display name.
    Bug: Unhandled NoneType / missing 'profile' key raises KeyError or AttributeError.
    """
    profile = record.get("profile")
    # Intentional null reference bug: profile might be None or dict without 'name'
    return profile["name"].title()
