"""Pull one free StatsBomb competition (default: 2018 FIFA World Cup) and load it
into Postgres as Competition / Team / Player / Match / PlayerMatchStat rows.

Safe to re-run: existing rows are matched on their StatsBomb id and updated
instead of duplicated.

Usage:
    python -m scripts.ingest_data
    python -m scripts.ingest_data --limit 3   # only the first 3 matches, for a quick test
"""

import argparse

import pandas as pd
import statsbombpy.sb as sb
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Competition, Match, Player, PlayerMatchStat, Team

COMPETITION_ID = 43  # FIFA World Cup
SEASON_ID = 3  # 2018


def timestamp_to_minutes(ts: str) -> float:
    """'MM:SS' or 'HH:MM:SS' -> minutes as a float. StatsBomb's clock is already
    cumulative across halves (e.g. a 2nd-half event reads ~65:00, not ~20:00)."""
    parts = [int(p) for p in ts.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
    else:
        _, minutes, seconds = parts
    return minutes + seconds / 60


def player_minutes_played(positions: list[dict], match_end_minute: float) -> int:
    total = 0.0
    for segment in positions:
        start = timestamp_to_minutes(segment["from"])
        end = timestamp_to_minutes(segment["to"]) if segment["to"] is not None else match_end_minute
        total += max(end - start, 0)
    return round(total)


def get_or_create(db: Session, model, match_kwargs: dict, defaults: dict | None = None):
    instance = db.query(model).filter_by(**match_kwargs).first()
    if instance:
        for key, value in (defaults or {}).items():
            setattr(instance, key, value)
        return instance
    instance = model(**match_kwargs, **(defaults or {}))
    db.add(instance)
    db.flush()  # assigns instance.id without a full commit
    return instance


def ingest_competition(db: Session) -> Competition:
    comps = sb.competitions()
    row = comps[
        (comps.competition_id == COMPETITION_ID) & (comps.season_id == SEASON_ID)
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


def ingest_player(db: Session, statsbomb_player_id: int, player_name: str, position: str | None) -> Player:
    return get_or_create(
        db,
        Player,
        {"statsbomb_player_id": statsbomb_player_id},
        {"player_name": player_name, "primary_position": position},
    )


def aggregate_player_stats(events: pd.DataFrame, player_name: str) -> dict:
    p = events[events["player"] == player_name]

    passes = p[p["type"] == "Pass"]
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


def ingest_match(db: Session, competition: Competition, sb_match_id: int, match_row: pd.Series) -> None:
    events = sb.events(match_id=sb_match_id)
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

    for team_name, lineup_df in lineups.items():
        team = home_team if team_name == match_row.home_team else away_team

        for _, lp in lineup_df.iterrows():
            position = lp["positions"][0]["position"] if lp["positions"] else None
            player = ingest_player(db, int(lp.player_id), lp.player_name, position)

            stat_defaults = {
                "position": position,
                "minutes_played": player_minutes_played(lp["positions"], match_end_minute),
                **aggregate_player_stats(events, lp.player_name),
            }
            get_or_create(
                db,
                PlayerMatchStat,
                {"match_id": match.id, "player_id": player.id},
                {"team_id": team.id, **stat_defaults},
            )


def main(limit: int | None):
    db = SessionLocal()
    try:
        competition = ingest_competition(db)
        db.commit()

        matches = sb.matches(competition_id=COMPETITION_ID, season_id=SEASON_ID)
        matches = matches.sort_values("match_date")
        if limit:
            matches = matches.head(limit)

        for i, (_, match_row) in enumerate(matches.iterrows(), start=1):
            print(f"[{i}/{len(matches)}] {match_row.home_team} {match_row.home_score}-{match_row.away_score} {match_row.away_team}")
            ingest_match(db, competition, int(match_row.match_id), match_row)
            db.commit()

        print("Done.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="only ingest the first N matches")
    args = parser.parse_args()
    main(limit=args.limit)
