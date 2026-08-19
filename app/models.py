from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Competition(Base):
    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    statsbomb_competition_id: Mapped[int] = mapped_column(Integer, unique=True)
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
    player_name: Mapped[str] = mapped_column(String(150))
    primary_position: Mapped[str | None] = mapped_column(String(50), nullable=True)

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
    """One row per player per match: basic aggregated performance stats
    derived from StatsBomb event data (passes, shots, defensive actions)."""

    __tablename__ = "player_match_stats"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    position: Mapped[str | None] = mapped_column(String(50), nullable=True)

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
