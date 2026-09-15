---
name: badminton-db
description: >-
  Query the badminton match database (a player's matches, shot-by-shot statistics such as
  shot-type counts and reasons for winning or losing points, scores, and rally clips featuring
  specific tactics or shot types). For questions about existing match data in the database,
  consult this playbook before calling badminton-db MCP tools.
---

# badminton-db playbook

Always access the database through **badminton-db MCP** tools (do not run shell commands yourself):

- `list_tables()` → list available tables
- `describe_table(table)` → inspect a table's columns
- `query(sql)` → run a **single SELECT**, returning `{rows, row_count}` (up to 200 rows)

## Rules

1. Submit only a **single SELECT** (multiple statements and DELETE/UPDATE/INSERT are rejected).
2. **Rally video clips**: always use `WHERE has_video=1` and return only rallies with actual video files; the database has many shot annotations but few rallies with video.
3. Shot types and reasons for winning or losing points are **Chinese enums**; players use `A`/`B`, mapped to names by `matches.player_a/player_b`. See `references/schema.md` for all columns and enums.
5. Advanced metrics (running distance, shot height, post-smash recovery speed, shot winner rate…) **are not in this DB**:
   first look up the match's `analyze_match_id` here, then follow the **badminton-analyze** skill to call that MCP.
4. When generating highlights, pass `matches.name` (without .mp4) as the reels `match_name`.

## Common queries

```sql
-- A player's matches (also retrieve analyze_match_id for advanced analysis)
SELECT name, tournament, round, year, analyze_match_id
FROM matches WHERE name LIKE '%AXELSEN%' ORDER BY year DESC;

-- Points won with a shot type by a player (the shot itself is the winner). ⚠️ Without match_name, this sums 138 matches!
SELECT COUNT(*) FROM shots
WHERE match_name='Viktor_AXELSEN_LEE_Zii_Jia_EAST_VENTURES_Indonesia_Open_2022_Semifinals'
  AND type='殺球' AND player='A' AND win_reason IS NOT NULL;

-- Distribution of reasons for losing points (single match: match_name is required; omitting it queries the whole DB)
SELECT lose_reason, COUNT(*) n FROM shots
WHERE match_name='<matches.name>' AND lose_reason IS NOT NULL GROUP BY lose_reason ORDER BY n DESC;

-- Compare the two players' use of a shot type (single match)
SELECT player, COUNT(*) n FROM shots WHERE match_name='<matches.name>' AND type='挑球' GROUP BY player;

-- Scores for three games (single match)
SELECT set_no, MAX(score_a) a, MAX(score_b) b FROM rallies
WHERE match_name='<matches.name>' GROUP BY set_no ORDER BY set_no;

-- Rallies with video clips (list those with files first)
SELECT rally_id, video_filename FROM rallies
WHERE match_name='<matches.name>' AND has_video=1 ORDER BY rally_id;
```

> Reminder:
> - `rallies`/`shots` use **`match_name`** (= `matches.name`, without .mp4) as the key. `matches` contains
>   **194 matches** (2022–2024); **138** have shot-by-shot `shots` and 169 have `rallies`. **For a specific match, always use**
>   `WHERE match_name = '<matches.name>'`—otherwise you sum all 138 matches (many matches share players or
>   tournament names across years; this is the most common source of incorrect answers). First find the match_name
>   with `name LIKE` on `matches`; the same pair of players may have multiple matches, so narrow by
>   `tournament` / `year` / `round` as needed.
> - rally_id is `set_scoreA_scoreB` (e.g. `1_05_04`) and corresponds to `video_filename`. To link a shot type to an actual video, first get rallies with files using `has_video=1`, then match `shots` by `set_no` + score.
