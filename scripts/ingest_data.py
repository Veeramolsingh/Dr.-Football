"""Pull free StatsBomb competitions into Postgres as
Competition / Team / Player / Match / PlayerMatchStat rows.

Player and team ids are global and stable across StatsBomb competitions
(verified: the same person keeps one id across the 2018 and 2022 World Cups),
so ingesting several tournaments merges cleanly -- a returning player reuses his
existing row, a new player gets a new one.

Safe to re-run: rows are matched on their StatsBomb id and updated in place.

Usage:
    python -m scripts.ingest_data                  # every competition in COMPETITIONS
    python -m scripts.ingest_data --limit 3        # first 3 matches of each, for a quick test
    python -m scripts.ingest_data --only 43:106    # just one competition:season
"""

import argparse
import unicodedata
from collections import Counter

import pandas as pd
import statsbombpy.sb as sb
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Competition, Match, Player, PlayerMatchStat, Team
from app.positions import normalise, unmapped

# (competition_id, season_id) pairs to ingest.
COMPETITIONS = [
    (43, 3),    # FIFA World Cup 2018
    (43, 106),  # FIFA World Cup 2022
]

# StatsBomb records a penalty shootout as period 5, and its penalties appear as
# ordinary Shot events with shot_outcome='Goal'. Football does not count those
# as goals -- a 3-3 final decided on penalties leaves both scorers on their
# open-play tally -- so counting them inflated Mbappe to 9 goals in 2022 (8 real
# + 1 shootout) and Messi to 9 (7 + two shootouts). Shootout events are dropped
# entirely: they also skew the match's last recorded minute, which is what
# minutes_played is measured against.
SHOOTOUT_PERIOD = 5


def timestamp_to_minutes(ts: str) -> float:
    """'MM:SS' or 'HH:MM:SS' -> minutes as a float. StatsBomb's clock is already
    cumulative across halves (e.g. a 2nd-half event reads ~65:00, not ~20:00)."""
    parts = [int(p) for p in ts.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
    else:
        _, minutes, seconds = parts
    return minutes + seconds / 60


def segment_minutes(segment: dict, match_end_minute: float) -> float:
    start = timestamp_to_minutes(segment["from"])
    end = timestamp_to_minutes(segment["to"]) if segment["to"] is not None else match_end_minute
    return max(end - start, 0)


def player_minutes_played(positions: list[dict], match_end_minute: float) -> int:
    return round(sum(segment_minutes(s, match_end_minute) for s in positions))


def main_position(positions: list[dict], match_end_minute: float) -> str | None:
    """The position a player spent the most minutes in during this match.

    A player can switch role mid-game (e.g. full back -> winger after a red
    card), so taking positions[0] would misattribute their stats.
    """
    if not positions:
        return None
    return max(positions, key=lambda s: segment_minutes(s, match_end_minute))["position"]


def get_or_create(db: Session, model, match_kwargs: dict, defaults: dict | None = None):
    """Fetch a row by its natural key, updating it if present, inserting if not.

    None values in `defaults` are skipped on update so a later, sparser record
    can never blank out a field an earlier one populated.
    """
    instance = db.query(model).filter_by(**match_kwargs).first()
    if instance:
        for key, value in (defaults or {}).items():
            if value is not None:
                setattr(instance, key, value)
        return instance
    instance = model(**match_kwargs, **(defaults or {}))
    db.add(instance)
    db.flush()  # assigns instance.id without a full commit
    return instance


def ingest_competition(db: Session, competition_id: int, season_id: int) -> Competition:
    comps = sb.competitions()
    row = comps[
        (comps.competition_id == competition_id) & (comps.season_id == season_id)
    ].iloc[0]
    return get_or_create(
        db,
        Competition,
        {"statsbomb_competition_id": int(row.competition_id), "statsbomb_season_id": int(row.season_id)},
        {"competition_name": row.competition_name, "season_name": row.season_name},
    )


def ingest_team(db: Session, statsbomb_team_id: int, team_name: str) -> Team:
    return get_or_create(
        db, Team, {"statsbomb_team_id": statsbomb_team_id}, {"team_name": team_name}
    )


def fold_accents(value: str) -> str:
    """'Kylian Mbappe Lottin' from 'Kylian Mbappé Lottin' -- decompose to base
    characters plus combining marks, then drop the marks. Users type names
    without accents, so matching has to happen on a folded form."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def build_search_name(player_name: str, nickname: str | None) -> str:
    parts = [player_name, nickname or ""]
    return fold_accents(" ".join(p for p in parts if p)).lower()


def ingest_player(db: Session, statsbomb_player_id: int, player_name: str, nickname: str | None) -> Player:
    # primary_position is deliberately not set here -- see backfill_primary_positions()
    return get_or_create(
        db,
        Player,
        {"statsbomb_player_id": statsbomb_player_id},
        {
            "player_name": player_name,
            "player_nickname": nickname,
            "search_name": build_search_name(player_name, nickname),
        },
    )


def aggregate_player_stats(events: pd.DataFrame, player_name: str) -> dict:
    p = events[events["player"] == player_name]

    passes = p[p["type"] == "Pass"]
    # NOTE: StatsBomb leaves pass_outcome empty on a *successful* pass and only
    # fills it in on failure -- the opposite of the intuitive reading.
    passes_completed = passes["pass_outcome"].isna().sum() if "pass_outcome" in passes else len(passes)

    shots = p[p["type"] == "Shot"]
    goals = (shots["shot_outcome"] == "Goal").sum() if "shot_outcome" in shots else 0

    assists = 0
    if "pass_goal_assist" in passes.columns:
        assists = (passes["pass_goal_assist"] == True).sum()  # noqa: E712 (NaN == True -> False, which is what we want)

    duels = p[p["type"] == "Duel"]
    tackles = (duels["duel_type"] == "Tackle").sum() if "duel_type" in duels else 0

    dribbles = p[p["type"] == "Dribble"]
    dribbles_completed = (
        (dribbles["dribble_outcome"] == "Complete").sum() if "dribble_outcome" in dribbles else 0
    )

    interceptions = (p["type"] == "Interception").sum()

    return {
        "passes_attempted": int(len(passes)),
        "passes_completed": int(passes_completed),
        "pass_completion_rate": float(round(passes_completed / len(passes), 3)) if len(passes) else 0.0,
        "shots": int(len(shots)),
        "goals": int(goals),
        "assists": int(assists),
        "tackles": int(tackles),
        "interceptions": int(interceptions),
        "dribbles_completed": int(dribbles_completed),
    }


def ingest_match(db: Session, competition: Competition, sb_match_id: int, match_row: pd.Series) -> int:
    """Returns the number of appearances stored for this match."""
    events = sb.events(match_id=sb_match_id)
    events = events[events["period"] != SHOOTOUT_PERIOD]
    lineups = sb.lineups(match_id=sb_match_id)

    # statsbombpy's matches() only gives team names, not ids -> pull ids from events
    team_ids_by_name = events[["team", "team_id"]].drop_duplicates().set_index("team")["team_id"].to_dict()
    home_team = ingest_team(db, int(team_ids_by_name[match_row.home_team]), match_row.home_team)
    away_team = ingest_team(db, int(team_ids_by_name[match_row.away_team]), match_row.away_team)

    match = get_or_create(
        db,
        Match,
        {"statsbomb_match_id": sb_match_id},
        {
            "competition_id": competition.id,
            "match_date": str(match_row.match_date),
            "home_team_id": home_team.id,
            "away_team_id": away_team.id,
            "home_score": int(match_row.home_score),
            "away_score": int(match_row.away_score),
        },
    )

    match_end_minute = float(events["minute"].max())
    appearances = 0

    for team_name, lineup_df in lineups.items():
        team = home_team if team_name == match_row.home_team else away_team

        for _, lp in lineup_df.iterrows():
            # An empty positions list means the player was named in the squad but
            # never came on. A non-appearance has no stats, so we skip it entirely
            # rather than storing a row of zeros that would skew every average.
            position = main_position(lp["positions"], match_end_minute)
            if position is None:
                continue

            role, group = normalise(position)
            # pandas yields NaN (a float), not None, for a missing nickname
            nickname = lp.get("player_nickname")
            nickname = None if nickname is None or pd.isna(nickname) else str(nickname)
            player = ingest_player(db, int(lp.player_id), lp.player_name, nickname)

            get_or_create(
                db,
                PlayerMatchStat,
                {"match_id": match.id, "player_id": player.id},
                {
                    "team_id": team.id,
                    "position": position,
                    "position_role": role,
                    "position_group": group,
                    "minutes_played": player_minutes_played(lp["positions"], match_end_minute),
                    **aggregate_player_stats(events, lp.player_name),
                },
            )
            appearances += 1

    return appearances


def backfill_primary_positions(db: Session) -> None:
    """Set each player's primary position to the one they appeared in most often.

    Done as a pass over the finished data rather than per-match, so match order
    can't matter and a single appearance out of position can't misrepresent them.
    """
    updated = 0
    for player in db.query(Player).all():
        positions = [s.position for s in player.stats if s.position]
        if not positions:
            continue
        most_common = Counter(positions).most_common(1)[0][0]
        role, group = normalise(most_common)
        player.primary_position = most_common
        player.primary_position_role = role
        player.primary_position_group = group
        updated += 1
    db.commit()
    print(f"Backfilled primary position for {updated} players.")


def main(limit: int | None, only: tuple[int, int] | None):
    competitions = [only] if only else COMPETITIONS
    db = SessionLocal()
    try:
        for competition_id, season_id in competitions:
            competition = ingest_competition(db, competition_id, season_id)
            db.commit()
            print(f"\n=== {competition.competition_name} {competition.season_name} ===")

            matches = sb.matches(competition_id=competition_id, season_id=season_id)
            matches = matches.sort_values("match_date")
            if limit:
                matches = matches.head(limit)

            for i, (_, match_row) in enumerate(matches.iterrows(), start=1):
                n = ingest_match(db, competition, int(match_row.match_id), match_row)
                db.commit()
                print(
                    f"[{i}/{len(matches)}] {match_row.home_team} {match_row.home_score}"
                    f"-{match_row.away_score} {match_row.away_team}  ({n} appearances)"
                )

        backfill_primary_positions(db)

        # Surface any position labels app.positions doesn't know about, so they
        # don't silently become NULL groups.
        seen = {p for (p,) in db.query(PlayerMatchStat.position).distinct()}
        if missing := unmapped(seen):
            print(f"WARNING: unmapped positions (add to app/positions.py): {sorted(missing)}")

        print("Done.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="only ingest the first N matches of each competition")
    parser.add_argument("--only", type=str, default=None, help="ingest a single 'competition_id:season_id'")
    args = parser.parse_args()
    only = tuple(int(x) for x in args.only.split(":")) if args.only else None
    main(limit=args.limit, only=only)
