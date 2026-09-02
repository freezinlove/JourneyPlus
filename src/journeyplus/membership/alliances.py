from __future__ import annotations

from journeyplus.membership.contracts import AirlineAlliance
from journeyplus.membership.normalization import normalize_key


# Manually curated from the three alliances' official member directories.
# This is deliberately a versioned runtime dataset instead of a live network call:
# graph rendering stays deterministic and a changed membership cannot silently alter
# previously generated results.
ALLIANCE_DIRECTORY_AS_OF = "2026-09-01"
ALLIANCE_DIRECTORY_SOURCES = {
    AirlineAlliance.STAR_ALLIANCE: "https://www.staralliance.com/en/members",
    AirlineAlliance.SKYTEAM: "https://www.skyteam.com/en/about/our-members/",
    AirlineAlliance.ONEWORLD: "https://www.oneworld.com/members",
}

ALLIANCE_MEMBER_AIRLINES: dict[AirlineAlliance, frozenset[str]] = {
    AirlineAlliance.STAR_ALLIANCE: frozenset(
        {
            "Aegean Airlines",
            "Air Canada",
            "Air China",
            "Air India",
            "Air New Zealand",
            "All Nippon Airways",
            "Asiana Airlines",
            "Austrian Airlines",
            "Avianca",
            "Brussels Airlines",
            "Copa Airlines",
            "Croatia Airlines",
            "EgyptAir",
            "Ethiopian Airlines",
            "EVA Air",
            "ITA Airways",
            "LOT Polish Airlines",
            "Lufthansa",
            "Shenzhen Airlines",
            "Singapore Airlines",
            "South African Airways",
            "SWISS International Air Lines",
            "TAP Air Portugal",
            "Thai Airways International",
            "Turkish Airlines",
            "United Airlines",
        }
    ),
    AirlineAlliance.SKYTEAM: frozenset(
        {
            "Aerolíneas Argentinas",
            "Aeromexico",
            "Air Europa",
            "Air France",
            "China Airlines",
            "China Eastern Airlines",
            "Delta Air Lines",
            "Garuda Indonesia",
            "Kenya Airways",
            "KLM Royal Dutch Airlines",
            "Korean Air",
            "Middle East Airlines",
            "SAS",
            "Saudia",
            "TAROM",
            "Vietnam Airlines",
            "Virgin Atlantic",
            "XiamenAir",
        }
    ),
    AirlineAlliance.ONEWORLD: frozenset(
        {
            "Alaska Airlines",
            "American Airlines",
            "British Airways",
            "Cathay Pacific",
            "Fiji Airways",
            "Finnair",
            "Hawaiian Airlines",
            "Iberia",
            "Japan Airlines",
            "Malaysia Airlines",
            "Oman Air",
            "Qantas",
            "Qatar Airways",
            "Royal Air Maroc",
            "Royal Jordanian",
            "SriLankan Airlines",
        }
    ),
}


# The unified graph stores loyalty-program names rather than carrier names.  These
# aliases bridge those two vocabularies. Airline names above are indexed as aliases
# automatically, so the explicit list only needs programme and common display names.
_PROGRAM_ALIASES: dict[AirlineAlliance, frozenset[str]] = {
    AirlineAlliance.STAR_ALLIANCE: frozenset(
        {
            "Aegean Miles+Bonus",
            "Aeroplan",
            "Air Canada Aeroplan",
            "Air China PhoenixMiles",
            "Air India Maharaja Club",
            "Air New Zealand Airpoints",
            "ANA",
            "ANA Mileage Club",
            "Asiana Club",
            "Austrian Miles & More",
            "Avianca LifeMiles",
            "Brussels Airlines Miles & More",
            "Copa Airlines ConnectMiles",
            "Croatia Airlines Miles & More",
            "EgyptAir Plus",
            "Ethiopian Airlines ShebaMiles",
            "EVA Air Infinity MileageLands",
            "ITA Airways Volare",
            "LOT Polish Airlines Miles & More",
            "Lufthansa Miles & More",
            "Miles & More",
            "Singapore Airlines KrisFlyer",
            "South African Airways Voyager",
            "SWISS Miles & More",
            "TAP Miles&Go",
            "Thai Airways Royal Orchid Plus",
            "Turkish Airlines Miles&Smiles",
            "United MileagePlus",
        }
    ),
    AirlineAlliance.SKYTEAM: frozenset(
        {
            "Aerolineas Plus",
            "Aeromexico Rewards",
            "Air Europa SUMA",
            "Air France Flying Blue",
            "Air France KLM",
            "Air France KLM Flying Blue",
            "Asante Rewards",
            "China Airlines Dynasty Flyer",
            "China Eastern Eastern Miles",
            "Delta SkyMiles",
            "Flying Blue",
            "GarudaMiles",
            "Kenya Airways Asante Rewards",
            "KLM Flying Blue",
            "Korean Air SKYPASS",
            "Lotusmiles",
            "Middle East Airlines Cedar Miles",
            "SAS EuroBonus",
            "Saudia AlFursan",
            "TAROM Flying Blue",
            "Vietnam Airlines Lotusmiles",
            "Virgin Atlantic Flying Club",
            "XiamenAir Egret Club",
        }
    ),
    AirlineAlliance.ONEWORLD: frozenset(
        {
            "Alaska Airlines Atmos Rewards",
            "Alaska Airlines Mileage Plan",
            "American Airlines AAdvantage",
            "British Airways Club",
            "Cathay",
            "Cathay Pacific Cathay",
            "Fiji Airways Tabua Club",
            "Finnair Plus",
            "Hawaiian Airlines Atmos Rewards",
            "HawaiianMiles",
            "Iberia Club",
            "Japan Airlines Mileage Bank",
            "Malaysia Airlines Enrich",
            "Oman Air Sindbad",
            "Qantas Frequent Flyer",
            "Qatar Airways Privilege Club",
            "Royal Air Maroc Safar Flyer",
            "Royal Jordanian Royal Club",
            "Royal Club",
            "SriLankan Airlines FlySmiLes",
        }
    ),
}


def _build_alias_index() -> dict[str, AirlineAlliance]:
    index: dict[str, AirlineAlliance] = {}
    for alliance, airlines in ALLIANCE_MEMBER_AIRLINES.items():
        for value in (*airlines, *_PROGRAM_ALIASES[alliance]):
            key = normalize_key(value)
            previous = index.get(key)
            if previous is not None and previous != alliance:
                raise RuntimeError(f"航空联盟别名冲突：{value}")
            index[key] = alliance
    return index


_ALLIANCE_BY_ALIAS = _build_alias_index()
_ALIASES_BY_LENGTH = tuple(
    sorted(_ALLIANCE_BY_ALIAS, key=lambda value: (-len(value.split()), -len(value)))
)


def airline_alliance(program: str) -> AirlineAlliance | None:
    """Resolve a graph programme/carrier label without making a fuzzy guess."""

    normalized = normalize_key(program)
    direct = _ALLIANCE_BY_ALIAS.get(normalized)
    if direct is not None:
        return direct
    for alias in _ALIASES_BY_LENGTH:
        if normalized.startswith(f"{alias} ") or normalized.endswith(f" {alias}"):
            return _ALLIANCE_BY_ALIAS[alias]
    return None
