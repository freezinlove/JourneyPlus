from journeyplus.membership.alliances import (
    ALLIANCE_DIRECTORY_AS_OF,
    ALLIANCE_MEMBER_AIRLINES,
    airline_alliance,
)
from journeyplus.membership.contracts import AirlineAlliance


def test_official_alliance_member_directory_is_complete_for_snapshot_date() -> None:
    assert ALLIANCE_DIRECTORY_AS_OF == "2026-09-01"
    assert len(ALLIANCE_MEMBER_AIRLINES[AirlineAlliance.STAR_ALLIANCE]) == 26
    assert len(ALLIANCE_MEMBER_AIRLINES[AirlineAlliance.SKYTEAM]) == 18
    assert len(ALLIANCE_MEMBER_AIRLINES[AirlineAlliance.ONEWORLD]) == 16

    assert "ITA Airways" in ALLIANCE_MEMBER_AIRLINES[AirlineAlliance.STAR_ALLIANCE]
    assert "Asiana Airlines" in ALLIANCE_MEMBER_AIRLINES[
        AirlineAlliance.STAR_ALLIANCE
    ]
    assert "SAS" in ALLIANCE_MEMBER_AIRLINES[AirlineAlliance.SKYTEAM]
    assert "Hawaiian Airlines" in ALLIANCE_MEMBER_AIRLINES[
        AirlineAlliance.ONEWORLD
    ]


def test_current_project_program_names_resolve_to_their_alliance() -> None:
    assert airline_alliance("lufthansa miles more") == AirlineAlliance.STAR_ALLIANCE
    assert airline_alliance("Flying Blue") == AirlineAlliance.SKYTEAM
    assert (
        airline_alliance("Kenya Airways Asante Rewards")
        == AirlineAlliance.SKYTEAM
    )
    assert airline_alliance("Lotusmiles Status Match") == AirlineAlliance.SKYTEAM
    assert (
        airline_alliance("Royal Jordanian Royal Club")
        == AirlineAlliance.ONEWORLD
    )


def test_non_member_programs_are_not_guessed() -> None:
    assert airline_alliance("Air Astana Nomad Club") is None
    assert airline_alliance("GHA DISCOVERY") is None
    assert airline_alliance("Club Avolta") is None
    assert airline_alliance("Aeroflot Bonus") is None
    assert airline_alliance("S7 Priority") is None
    assert airline_alliance("Philippine Airlines Mabuhay Miles") is None
