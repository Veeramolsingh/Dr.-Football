"""A description of our database handed to the SQL Agent as its map of the
schema. Hand-written rather than auto-generated from app.models: the LLM needs
semantic hints (which column to prefer, what NULL means, how to avoid a
small-sample-size fluke) that a plain column dump wouldn't carry.
"""

SCHEMA_DESCRIPTION = """
PostgreSQL database of football match statistics from StatsBomb open data
(2018 and 2022 FIFA World Cups).

TABLE competitions
  id                  integer, primary key
  competition_name    text, e.g. 'FIFA World Cup'
  season_name         text, e.g. '2018' or '2022'

TABLE teams
  id                  integer, primary key
  team_name           text, e.g. 'Brazil'

TABLE players
  id                       integer, primary key
  player_name              text, FULL legal name as registered, e.g.
                            'Cristiano Ronaldo dos Santos Aveiro',
                            'Kleper Laveran Lima Ferreira'. Almost never what a
                            user types. Do NOT match against this column.
  player_nickname          text, the common name, e.g. 'Cristiano Ronaldo',
                            'Pepe', 'Lionel Messi'. May be NULL. Good for
                            DISPLAY, but still accented, so don't match on it.
  search_name              text, lowercase and accent-stripped, containing BOTH
                            the full name and the nickname. THIS is the only
                            column to match a user-typed player name against:
                              WHERE p.search_name LIKE '%ronaldo%'
                            Lowercase your search term and strip its accents
                            (mbappe, not Mbappé). Match on the most distinctive
                            single word (a surname), not the whole phrase.
  primary_position         text, raw StatsBomb label, e.g. 'Left Center Back'
  primary_position_role    text, e.g. 'Center Back' (their most-played role, ACROSS ALL matches)
  primary_position_group   text, one of: Goalkeeper, Defender, Midfielder, Forward
  -- primary_position* describes the player overall. Prefer the same columns on
  -- player_match_stats instead when the question is about a specific match/appearance.

TABLE matches
  id              integer, primary key
  competition_id  -> competitions.id
  match_date      text (ISO date)
  home_team_id    -> teams.id
  away_team_id    -> teams.id
  home_score      integer
  away_score      integer

TABLE player_match_stats
  -- One row per player per match THEY ACTUALLY APPEARED IN. Players named in a
  -- squad but never brought on are not stored here at all, so no "did they play"
  -- filter is ever needed -- every row is a real appearance.
  id                    integer, primary key
  match_id              -> matches.id
  player_id             -> players.id
  team_id               -> teams.id
  position              text, raw StatsBomb label for THIS match, e.g. 'Right Back'
  position_role         text, unified role for THIS match. USE THIS COLUMN for
                         questions about a role/position (e.g. "center-backs",
                         "wingers") -- it collapses Left/Right/Center variants into
                         one label. Valid values: Goalkeeper, Full Back, Wing Back,
                         Center Back, Defensive Midfield, Central Midfield,
                         Attacking Midfield, Wide Midfield, Winger, Striker,
                         Second Striker
  position_group        text, one of: Goalkeeper, Defender, Midfielder, Forward
  minutes_played         integer
  passes_attempted        integer
  passes_completed        integer
  pass_completion_rate    float, 0.0-1.0 for THIS match. When aggregating across
                           several matches, do NOT average this column directly --
                           recompute it as
                           SUM(passes_completed)::float / NULLIF(SUM(passes_attempted), 0)
  shots                  integer
  goals                  integer
  assists                integer
  tackles                integer
  interceptions           integer
  dribbles_completed       integer

RULES
- Write exactly one PostgreSQL SELECT statement. Never write INSERT, UPDATE,
  DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, or any statement that changes
  data or schema.
- When ranking players by an average or rate (pass completion, etc.), always add
  a minimum-sample-size filter, e.g. HAVING SUM(passes_attempted) >= 100 or
  HAVING COUNT(*) >= 3. Without it, a player with a single lucky match tops
  every list.
- A position word in a question about NAMED players is descriptive, not a
  filter. "Who is the better striker, Mbappe or Ronaldo?" asks you to compare
  those two players' records -- it does NOT mean "only count matches where they
  lined up as a Striker". Players move around: Mbappe has 12 goals across these
  tournaments, but only 1 appearance recorded at 'Striker', so filtering him by
  position_role silently throws away 11 of his 14 appearances and reports 3
  goals as if it were his whole record.
  Filter on position ONLY when the question asks for a CATEGORY of player with
  nobody named ("find me the best center-backs"). When individuals are named,
  aggregate all their appearances.
- When a question is about specific named players, ALWAYS select and GROUP BY
  the player's name alongside any aggregate. A bare `SELECT SUM(goals) ... WHERE
  <name>` returns one row of NULL when the name matches nobody, which reads
  downstream as a confident "0 goals" for a player we never found. Grouping by
  name makes a miss return zero rows instead, which is honestly empty.
- A ranking question ("top scorers", "best passers", "who scored the most")
  wants the leaders, not every qualifying player. Use LIMIT -- the number they
  asked for, or 10 if they didn't say. Never return a long tail of rows that
  merely satisfy the filter.
- The one exception: when the question narrows an already-established group
  from earlier in the conversation ("which of THEM played the most minutes?"),
  return that whole small group ordered by the metric instead of LIMIT 1, so
  the top answer can be described against the others.
- Return ONLY the SQL. No explanation, no markdown code fences.
"""
