---
name: badminton-analyze
description: >-
  Analyze badminton singles matches with badminton-analyze MCP tools. Use when the user wants a
  match's shot effectiveness, lost-point locations, rally rest times, running distance, backcourt
  usage, shot height, post-smash movement, or statistics verification — for a CoachAI match_id
  (matches.analyze_match_id) or a 2025/2026 Plan 3 game_id (2025gameN / 2026gameN).
---

# Badminton singles match analysis

Produce verifiable tactical analysis from match data returned by the MCP Server. The current official analysis scope focuses on singles. Use the following when calling tools:

```json
{
  "match_id": "200",
  "match_type": "single"
}
```

## Before starting analysis

- `match_id` is **CoachAI's numeric id**, stored in badminton-db as `matches.analyze_match_id` — not
  our match name (passing a name returns `Failed to fetch set data: 400`). Look it up with
  badminton-db first; if the user already gave a numeric `match_id`, use it directly without asking again.
- If neither a `match_id` nor an identifiable match is available, ask the user first.
- Keep `match_id` as a string; do not guess or substitute it.
- Always use `"single"` for `match_type` unless the user explicitly requests another scope.
- If the match is `2025gameN` or `2026gameN` (`analyze_match_id` is NULL for these), it is Plan 3
  local CSV data: do not pass it to the legacy API tools, and do not add `match_type`. See Plan 3 below.
- If a tool result has `isError=true`, do not invent values. If the content contains
  `BADMINTON_TOOL_ERROR:`, parse the JSON after the marker for `error.code`, `message`, and
  `retryable`; explain the safe message to the user, and include `error_id` when operators may need
  to trace it.
- `retryable=true` only means a limited number of retries is appropriate; never resend indefinitely.
  A session 404 must be fixed by the MCP client clearing the old session and re-initializing, not by
  the model calling the same tool repeatedly.

## Available tools

| MCP tool | Purpose |
| --- | --- |
| `get_backcourt_count` | Count each player's backcourt shots and provide related rally details |
| `get_shot_height` | Count each player's shots above and below net height |
| `get_lost_point_distribution` | Summarize each player's lost-point distribution across zones 1–16 |
| `get_rally_rest_time` | Calculate rest time in seconds between adjacent rallies in the same game |
| `get_running_distance` | Calculate total running distance, average distance per rally, and average distance per shot |
| `get_shot_win_rate` | Calculate attempts, winners, and win_rate for each shot type |
| `get_smash_followup_speed` | Calculate movement speed toward the service line or central area after a smash |
| `verify_match_statistics` | Recalculate from raw match data and verify the highest or lowest statistics |
| `get_plan3_shot_win_rate` | Shot-type winner rate for Plan 3 (2025–2026 auto-annotated CSV) games |
| `get_plan3_rally_rest_time` | Rally rest time for Plan 3 (2025–2026 auto-annotated CSV) games |

These are the public MCP tool names. Do not use `register_*_tools`; those are internal Python registration functions.
All tools are **synchronous** — no job polling.

## Plan 3 (2025–2026 auto-annotated data)

When the match is `2025gameN` or `2026gameN`, use only these two Plan 3 tools, with the game id
(= `matches.name`) as `game_id`:

```json
{ "game_id": "2025game1" }
```

- Shot effectiveness: `get_plan3_shot_win_rate`
- Rally rest time: `get_plan3_rally_rest_time`

Plan 3 data has no reliable final landing location, shot height, or player/opponent stance data.
Therefore do not use it for lost-point locations, shot height, running distance, backcourt stance, or
post-smash movement; state directly that the data is insufficient, and do not substitute legacy API
match data. `verify_match_statistics` does not cover Plan 3 games either.

Plan 3 results carry `"data_source": "plan3_csv"` and the same shape as their legacy counterparts
(`summary` / `details` / `data_quality`). Their A/B binding equals ours (A = `matches.player_a`).

## Tool selection

When the user specifies an analysis, call only the relevant tools. For a full match analysis, call the first seven analysis tools and use `verify_match_statistics` to verify important extreme-value conclusions according to the rules below. For a full Plan 3 analysis, call the two Plan 3 tools and say which metrics are unavailable.

### Shot winner rate

Call:

```json
{
  "match_id": "200",
  "match_type": "single"
}
```

Use these fields from `get_shot_win_rate`:

- `players`: mapping from A and B (always the literal `"Player A"`/`"Player B"` — see Response format).
- `summary`: `attempts`, `winners`, and `win_rate` by player and shot type.
- `data_quality`: total rallies, valid rallies, total shots, valid shots, and skipped counts.

`win_rate` is a proportion from 0 to 1. You may display it as a percentage, but retain the original attempts and winners to avoid comparing only proportions from small samples.

### Lost-point distribution by zone

`get_lost_point_distribution` returns:

- `summary`: each player's proportion of lost points in each zone.
- `details`: the `lose zone` for each rally.
- `data_quality`: valid and skipped rally counts.

Valid zone codes are strings from `"1"` to `"16"`. They are the same court-area codes as badminton-db
`shots.hit_area` / `landing_area` (our DB-side recount of a match's lost-point zones reproduces this
tool's counts). The layout is **not** a 4×4 grid in reading order. It is a 3×3 in-court grid plus 7
out-of-bounds zones, numbered from the viewpoint of the player standing in that half and facing the net:

```
              net
   10 |  2 |  7 |  1 | 16     front court
   11 |  6 |  8 |  5 | 15     mid court
   12 |  4 |  9 |  3 | 14     rear court
                13            behind the baseline
 (left out) left mid right (right out)
```

- 1–9 are inside the singles court: 7/8/9 is the centre column; odd zones 1/5/3 are on the player's
  right, even zones 2/6/4 on the player's left.
- 10–16 are out of bounds: 10/11/12 outside the left sideline, 14/15/16 outside the right sideline,
  13 behind the baseline.
- Both halves use the same player-relative numbering, so they mirror on screen (the far player faces
  the camera, so the far half's zone 1 appears on the left of the frame).
- The layout was inferred from ~250k labelled hit/landing coordinates in the raw CSVs; no official
  mapping has been published and exact boundaries are unknown. Say so if precision matters.
- A lost-point zone is the landing code of the rally-ending shot, and that shot may be the player's
  **own** error, not the opponent's winner. A shot that goes out gets an out zone (10–16); a shot into
  the net still gets a front-court code (7/1/2). For example, a player's net shots that hit the net
  can make zone 1 their top lost-point zone. Before turning a zone into advice such as "attack this
  zone", check in badminton-db who hit the last shot and its `lose_reason`.

When drawing a court or heat map, always use this layout. Never place zones 1–16 in a 4×4 grid in
numeric order.

### Rally rest time

`get_rally_rest_time` uses seconds. Its summary includes:

- `average_rest_time`
- `max_rest_time`
- `min_rest_time`

`details` contains the `rally` and `rest_time` for adjacent rallies; `data_quality.rest_intervals` is the number of rest intervals actually established.

### Other action and movement metrics

- Use `get_backcourt_count` for backcourt counts.
- Use `get_shot_height` for shot height.
- Use `get_running_distance` for running distance; use the units returned by the tool and label them clearly in the report.
- Use `get_smash_followup_speed` for post-smash movement; speed is in m/s.

## Verify numerical conclusions

When claiming that a statistic is the "highest" or "lowest," verify it with `verify_match_statistics`. It currently supports singles and the following three metrics:

| metric | Verification |
| --- | --- |
| `shot_win_rate` | Highest or lowest winner rate by player and shot type |
| `lost_point_distribution` | Highest or lowest lost-point proportion by player and zone |
| `rally_rest_time` | Longest or shortest rally rest time |

Example call:

```json
{
  "match_id": "200",
  "match_type": "single",
  "metric": "shot_win_rate",
  "condition": "highest"
}
```

`condition` must be `"highest"` or `"lowest"`. The verification `summary` includes `metric`, `condition`, and the fields for that metric:

- `shot_win_rate`: `player`, `shot_type`, `attempts`, `winners`, `win_rate`.
- `lost_point_distribution`: `player`, `zone`, `lost_points`, `total_lost_points`, `rate`.
- `rally_rest_time`: `set`, `rally`, `rest_time`.

If the source and verification tools disagree, use the recalculated results from `verify_match_statistics` and explicitly identify the inconsistency; do not hide it.

## Interpret data quality

Official statistics tools may return `data_quality`. When analyzing:

- State valid sample counts such as `verified_rallies`, `valid_shots`, or `rest_intervals`.
- If `skipped_rallies` or `skipped_shots` exceeds 0, note that conclusions cover only verifiable data.
- A numeric `0` means the calculation returned zero; `null`, missing fields, or `error` mean the value could not be obtained or calculated. Do not conflate them.
- Do not infer player performance from missing details.

## Response format

The `players` field is always the literal `"Player A"`/`"Player B"` (legacy and Plan 3 alike). First
replace A and B with the real names from badminton-db `matches.player_a` / `matches.player_b`, then summarize:

1. Answer the user's specific question first.
2. Support conclusions with a few key numbers, including counts, proportions, and units.
3. Compare players using the same metrics and data scope.
4. If details are long, extract only rallies supporting the conclusion; do not dump the entire raw JSON.
5. Clearly distinguish direct tool results from tactical interpretations based on them.
6. For the three metrics supported by `verify_match_statistics`, include verification results with any formal "highest" or "lowest" conclusion; for other metrics (and all Plan 3 results), include source-tool values and valid sample counts.
