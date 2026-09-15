# badminton.db — schema and enum reference

## Table structure (actual columns)

```
matches(folder, name, tournament, round, player_a, player_b, year, is_practice,
        source, analyze_match_id)
  - folder      : folder name (including .mp4)
  - name        : readable name without .mp4 = match_name passed to reels
  - player_a/b  : correspond to 'A'/'B' in shots.player (populated for matches with RallySeg; otherwise NULL)
  - is_practice : 1=NYCU practice clip, 0=official match
  - year        : 2022 / 2023 / 2024
  - source      : 'hf' (HuggingFace dataset) or 'Data-old' (merged legacy dataset)
  - analyze_match_id : numeric CoachAI ID used by badminton-analyze MCP (NULL = advanced analysis unavailable for this match)

rallies(match_name, rally_id, set_no, score_a, score_b, start_frame, end_frame,
        has_video, video_filename)
  - match_name     : = matches.name (without .mp4). Both rallies/shots use this key to join matches
  - rally_id       : "set_scoreA_scoreB", e.g. 1_05_04
  - has_video      : 1=the file actually exists in rally_video/ (always filter by this column when retrieving clips)
  - video_filename : e.g. 1_05_04.mp4 (when has_video=1)

shots(match_name, set_no, rally, ball_round, player, server, type,
      aroundhead, backhand, hit_area, landing_area, lose_reason, win_reason,
      getpoint_player, roundscore_a, roundscore_b)
  - match_name  : = matches.name (without .mp4)
  - player / getpoint_player : 'A' | 'B' (player=the hitter; getpoint_player=the rally winner)
  - type        : shot type (Chinese enum; see below)
  - aroundhead/backhand : 0/1
  - win_reason  : non-NULL when this hitter makes the winning shot (e.g. 落地致勝 / 對手出界)
  - lose_reason : non-NULL when this hitter loses the point through an error (e.g. 出界 / 掛網)
  - roundscore_a/b : score at the time of the shot

```

## Enum values

- `type` (shot type): 放小球、挑球、擋小球、殺球、點扣、發短球、推球、切球、過度切球、勾球、長球、發長球、平球、撲球、後場抽平球、防守回抽、防守回挑、死球、小平球、未知球種
  (`死球` appears only in newer 2023/2024 matches; a few rows have an empty string for `type`.)
- `lose_reason`: 出界、對手落地致勝、未過網、掛網、落點判斷失誤
- `win_reason`: 對手出界、落地致勝、對手未過網、對手掛網、對手落點判斷失誤

These are literal stored values; retain them in queries. For example, `殺球` means smash, `挑球` means lift, `放小球` means net shot, `出界` means out of bounds, `掛網` means into the net, and `未知球種` means unknown shot type.

## Important conventions

- **A/B ↔ names**: A=`matches.player_a`, B=`matches.player_b`. For Axelsen vs Lee, for example, A=Viktor AXELSEN and B=LEE Zii Jia.
- **"Points won with a shot type"**: the shot itself is the winner → `type=... AND player=... AND win_reason IS NOT NULL`.
- **Current data coverage**: `matches` has 194 matches (189 official + 5 NYCU practice, 2022–2024); `rallies` covers 169 matches and `shots` covers **138** (the rest have catalog metadata only: practice clips or matches without annotation files). **Always filter by `match_name` for a specific match**, or you will sum across 138 matches (the most common source of errors).
- **Advanced analysis**: running distance, shot height, post-smash recovery speed, etc. are not in this DB → obtain `analyze_match_id`, then use the **badminton-analyze** skill.
- **Video clips**: there are many annotations but few actual videos → always filter with `has_video=1` before returning clips to users.
