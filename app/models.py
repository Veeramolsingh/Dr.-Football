from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Competition(Base):
    """One tournament-season, e.g. ('FIFA World Cup', '2018').

    Note the composite unique key: successive editions of the same tournament
    share a statsbomb_competition_id and differ only by season, so neither
    column is unique on its own.
    """

    __tablename__ = "competitions"
    __table_args__ = (
        UniqueConstraint("statsbomb_competition_id", "statsbomb_season_id", name="uq_competition_season"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    statsbomb_competition_id: Mapped[int] = mapped_column(Integer)
    statsbomb_season_id: Mapped[int] = mapped_column(Integer)
    competition_name: Mapped[str] = mapped_column(String(120))
    season_name: Mapped[str] = mapped_column(String(50))

    matches: Mapped[list["Match"]] = relationship(back_populates="competition")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    statsbomb_team_id: Mapped[int] = mapped_column(Integer, unique=True)
    team_name: Mapped[str] = mapped_column(String(120))


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    statsbomb_player_id: Mapped[int] = mapped_column(Integer, unique=True)

    # player_name is the full legal name StatsBomb records ("Kleper Laveran Lima
    # Ferreira"); player_nickname is what commentary actually calls them
    # ("Pepe"). search_name holds both, lowercased and stripped of accents, and
    # is the column to match user-typed names against -- people type "Mbappe"
    # and "Ronaldo", which match neither of the other two columns.
    player_name: Mapped[str] = mapped_column(String(150))
    player_nickname: Mapped[str | None] = mapped_column(String(150), nullable=True)
    search_name: Mapped[str] = mapped_column(String(300), index=True)

    # The position this player appeared in most often across all their matches.
    # Backfilled after ingestion (see scripts/ingest_data.py:backfill_primary_positions)
    # rather than written per-match, so a single benched appearance can't erase it.
    primary_position: Mapped[str | None] = mapped_column(String(50), nullable=True)
    primary_position_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    primary_position_group: Mapped[str | None] = mapped_column(String(20), nullable=True)

    stats: Mapped[list["PlayerMatchStat"]] = relationship(back_populates="player")


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    statsbomb_match_id: Mapped[int] = mapped_column(Integer, unique=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"))
    match_date: Mapped[str] = mapped_column(String(20))
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    home_score: Mapped[int] = mapped_column(Integer)
    away_score: Mapped[int] = mapped_column(Integer)

    competition: Mapped["Competition"] = relationship(back_populates="matches")
    home_team: Mapped["Team"] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped["Team"] = relationship(foreign_keys=[away_team_id])
    stats: Mapped[list["PlayerMatchStat"]] = relationship(back_populates="match")


class PlayerMatchStat(Base):
    """One row per player per match they actually appeared in: aggregated
    performance stats derived from StatsBomb event data.

    Players named in a matchday squad but never brought on are deliberately not
    stored -- a non-appearance has no stats, and keeping all-zero rows would
    silently drag down every AVG() the SQL agent writes.
    """

    __tablename__ = "player_match_stats"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))

    # position: raw StatsBomb label ("Left Center Back"); role/group are the
    # normalised tiers from app.positions so queries can filter at any level.
    position: Mapped[str] = mapped_column(String(50))
    position_role: Mapped[str] = mapped_column(String(50))
    position_group: Mapped[str | None] = mapped_column(String(20), nullable=True)

    minutes_played: Mapped[int] = mapped_column(Integer, default=0)
    passes_attempted: Mapped[int] = mapped_column(Integer, default=0)
    passes_completed: Mapped[int] = mapped_column(Integer, default=0)
    pass_completion_rate: Mapped[float] = mapped_column(Float, default=0.0)
    shots: Mapped[int] = mapped_column(Integer, default=0)
    goals: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    tackles: Mapped[int] = mapped_column(Integer, default=0)
    interceptions: Mapped[int] = mapped_column(Integer, default=0)
    dribbles_completed: Mapped[int] = mapped_column(Integer, default=0)

    match: Mapped["Match"] = relationship(back_populates="stats")
    player: Mapped["Player"] = relationship(back_populates="stats")
    team: Mapped["Team"] = relationship()
