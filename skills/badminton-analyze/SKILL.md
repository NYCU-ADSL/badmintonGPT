---
name: badminton-analyze
description: >-
  Analyze badminton singles matches with badminton-analyze MCP tools. Use when the user provides
  a match_id and requests shot effectiveness, lost-point locations, rally rest times, running
  distance, backcourt usage, shot height, post-smash movement, or statistics verification.
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

- If the user has provided a `match_id`, use it directly without asking again.
- If `match_id` is missing, ask the user to provide it first.
- Keep `match_id` as a string; do not guess or substitute it.
- Always use `"single"` for `match_type` unless the user explicitly requests another scope.
- If a tool returns an `error`, do not invent values; explain the failure and what data is missing.

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

These are the public MCP tool names. Do not use `register_*_tools`; those are internal Python registration functions.

## Tool selection

When the user specifies an analysis, call only the relevant tools. For a full match analysis, call the first seven analysis tools and use `verify_match_statistics` to verify important extreme-value conclusions according to the rules below.

### Shot winner rate

Call:

```json
{
  "match_id": "200",
  "match_type": "single"
}
```

Use these fields from `get_shot_win_rate`:

- `players`: mapping from A and B to actual player names.
- `summary`: `attempts`, `winners`, and `win_rate` by player and shot type.
- `data_quality`: total rallies, valid rallies, total shots, valid shots, and skipped counts.

`win_rate` is a proportion from 0 to 1. You may display it as a percentage, but retain the original attempts and winners to avoid comparing only proportions from small samples.

### Lost-point distribution by zone

`get_lost_point_distribution` returns:

- `summary`: each player's proportion of lost points in each zone.
- `details`: the `lose zone` for each rally.
- `data_quality`: valid and skipped rally counts.

Valid zone codes are strings from `"1"` to `"16"`. Without a complete zone mapping, retain the numeric codes; do not invent zone names.

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

First use `players` to replace A and B with actual names, then summarize:

1. Answer the user's specific question first.
2. Support conclusions with a few key numbers, including counts, proportions, and units.
3. Compare players using the same metrics and data scope.
4. If details are long, extract only rallies supporting the conclusion; do not dump the entire raw JSON.
5. Clearly distinguish direct tool results from tactical interpretations based on them.
6. For the three metrics supported by `verify_match_statistics`, include verification results with any formal "highest" or "lowest" conclusion; for other metrics, include source-tool values and valid sample counts.
