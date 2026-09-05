"""AIS ship-type code -> human-readable label mapping (business/presentation logic).

The AIS wire (and the ``vessels.ship_type`` column) uses the standard ITU/IMO
numeric ship-type codes; this module turns them into stable English labels for
API responses. Unknown codes return ``None`` rather than fabricating a value.
"""
from typing import Optional

SHIP_TYPE_LABELS: dict[int, str] = {
    20: "Wing in Ground",
    30: "Fishing",
    31: "Towing",
    32: "Towing (long/wide)",
    33: "Dredging / underwater ops",
    34: "Diving ops",
    35: "Military ops",
    36: "Sailing",
    37: "Pleasure craft",
    40: "High speed craft",
    50: "Pilot vessel",
    51: "Search and rescue vessel",
    52: "Tug",
    53: "Port tender",
    54: "Anti-pollution equipment",
    55: "Law enforcement",
    58: "Medical transport",
    59: "Non-combatant ship",
    60: "Passenger",
    70: "Cargo",
    80: "Tanker",
    90: "Other type",
}


def ship_type_label(code: Optional[int]) -> Optional[str]:
    """Return a human-readable label for an AIS ship-type code, else None."""
    if code is None:
        return None
    return SHIP_TYPE_LABELS.get(int(code))