"""Normalise StatsBomb's 25 granular position labels into coarser tiers.

StatsBomb records positions like "Left Center Back" / "Right Center Back" /
"Center Back" as three distinct values. A natural-language question such as
"find me the best center-backs" would otherwise force the Text-to-SQL agent to
guess a brittle LIKE pattern, so we precompute two extra tiers:

    position       "Left Center Back"   <- raw StatsBomb value, kept as-is
    position_role  "Center Back"        <- what a scout would call the role
    position_group "Defender"           <- broadest bucket

Queries can then filter on whichever tier the question implies.
"""

# raw StatsBomb position -> (role, group)
POSITION_MAP: dict[str, tuple[str, str]] = {
    "Goalkeeper": ("Goalkeeper", "Goalkeeper"),
    # --- defenders ---
    "Right Back": ("Full Back", "Defender"),
    "Left Back": ("Full Back", "Defender"),
    "Right Wing Back": ("Wing Back", "Defender"),
    "Left Wing Back": ("Wing Back", "Defender"),
    "Center Back": ("Center Back", "Defender"),
    "Right Center Back": ("Center Back", "Defender"),
    "Left Center Back": ("Center Back", "Defender"),
    # --- midfielders ---
    "Right Defensive Midfield": ("Defensive Midfield", "Midfielder"),
    "Left Defensive Midfield": ("Defensive Midfield", "Midfielder"),
    "Center Defensive Midfield": ("Defensive Midfield", "Midfielder"),
    "Right Center Midfield": ("Central Midfield", "Midfielder"),
    "Left Center Midfield": ("Central Midfield", "Midfielder"),
    "Center Midfield": ("Central Midfield", "Midfielder"),
    "Right Attacking Midfield": ("Attacking Midfield", "Midfielder"),
    "Left Attacking Midfield": ("Attacking Midfield", "Midfielder"),
    "Center Attacking Midfield": ("Attacking Midfield", "Midfielder"),
    "Right Midfield": ("Wide Midfield", "Midfielder"),
    "Left Midfield": ("Wide Midfield", "Midfielder"),
    # --- forwards ---
    "Right Wing": ("Winger", "Forward"),
    "Left Wing": ("Winger", "Forward"),
    "Center Forward": ("Striker", "Forward"),
    "Right Center Forward": ("Striker", "Forward"),
    "Left Center Forward": ("Striker", "Forward"),
    "Secondary Striker": ("Second Striker", "Forward"),
}

POSITION_GROUPS = ["Goalkeeper", "Defender", "Midfielder", "Forward"]


def normalise(position: str | None) -> tuple[str | None, str | None]:
    """('Left Center Back') -> ('Center Back', 'Defender').

    Unknown labels return (position, None) rather than raising, so a new
    competition with an unseen label still ingests; report_unmapped() surfaces
    them so the map can be extended.
    """
    if position is None:
        return None, None
    return POSITION_MAP.get(position, (position, None))


def unmapped(positions) -> set[str]:
    """Any position labels we don't have a mapping for."""
    return {p for p in positions if p and p not in POSITION_MAP}
