"""
Pattern mini-DSL for user-defined plate searches.

Wildcards:
  ?  = any alphanumeric character (A-Z, 0-9)
  #  = digit (0-9)
  @  = letter (A-Z)
  literal = fixed character (must be alphanumeric)

Examples:
  FL###   → FL000 … FL999
  007?    → 007A, 007B … 0070, 0071 … 007Z, 0079
  @@@00   → AAA00 … ZZZ00
  MIAMI   → just MIAMI (no wildcards)
"""
import itertools
import string

_CHARSET_MAP = {
    "?": string.ascii_uppercase + string.digits,
    "#": string.digits,
    "@": string.ascii_uppercase,
}


def pattern_plates(pattern: str):
    """Expand a pattern string into all matching plate strings."""
    pattern = pattern.upper().strip()
    if not pattern or len(pattern) > 7:
        return

    # Build a list of character-sets, one per position
    char_sets = []
    for ch in pattern:
        if ch in _CHARSET_MAP:
            char_sets.append(_CHARSET_MAP[ch])
        elif ch.isalnum():
            char_sets.append(ch)  # literal — single character string
        else:
            # Invalid character in pattern; skip entirely
            return

    # Wrap literals in a list so itertools.product works uniformly
    normalized = [list(cs) if isinstance(cs, str) and len(cs) > 1 else [cs] for cs in char_sets]

    for combo in itertools.product(*normalized):
        yield "".join(combo)


def estimate_pattern_count(pattern: str) -> int:
    """Return the number of combinations a pattern will generate."""
    pattern = pattern.upper().strip()
    count = 1
    for ch in pattern:
        if ch in _CHARSET_MAP:
            count *= len(_CHARSET_MAP[ch])
        elif ch.isalnum():
            pass  # literal: ×1
        else:
            return 0
    return count
