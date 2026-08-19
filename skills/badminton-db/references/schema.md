# badminton.db — schema 與 enum 對照卡

## 表結構（實際欄位）
```
matches(folder, name, tournament, round, player_a, player_b, year, is_practice,
        source, analyze_match_id)
  - folder      : 資料夾名（含 .mp4）
  - name        : 去 .mp4 的可讀名 = 傳給 reels 的 match_name
  - player_a/b  : 對應 shots.player 的 'A'/'B'（有 RallySeg 的比賽才填；其餘為 NULL）
  - is_practice : 1=NYCU 練習片, 0=正式賽事
  - year        : 2022 / 2023 / 2024
  - source      : 'hf'（HuggingFace 資料集）或 'Data-old'（併入的舊資料集）
  - analyze_match_id : badminton-analyze MCP 用的 CoachAI 數字 ID（NULL = 該場無法做進階分析）

rallies(match_name, rally_id, set_no, score_a, score_b, start_frame, end_frame,
        has_video, video_filename)
  - match_name     : = matches.name（不含 .mp4）。rallies/shots 都用這個 key join matches
  - rally_id       : "set_scoreA_scoreB"，如 1_05_04
  - has_video      : 1=rally_video/ 內實際有此檔（查片段務必過濾此欄）
  - video_filename : 例 1_05_04.mp4（has_video=1 時）

shots(match_name, set_no, rally, ball_round, player, server, type,
      aroundhead, backhand, hit_area, landing_area, lose_reason, win_reason,
      getpoint_player, roundscore_a, roundscore_b)
  - match_name  : = matches.name（不含 .mp4）
  - player / getpoint_player : 'A' | 'B'（player=擊此球者；getpoint_player=該回合得分者）
  - type        : 球種（中文 enum，見下）
  - aroundhead/backhand : 0/1
  - win_reason  : 此「擊球者」打出致勝球時非 NULL（如 落地致勝 / 對手出界）
  - lose_reason : 此「擊球者」自己失誤丟分時非 NULL（如 出界 / 掛網）
  - roundscore_a/b : 該球當下比分
```

## enum 取值
- `type`（球種）：放小球、挑球、擋小球、殺球、點扣、發短球、推球、切球、過度切球、勾球、長球、發長球、平球、撲球、後場抽平球、防守回抽、防守回挑、死球、小平球、未知球種
  （`死球` 只出現在較新的 2023/2024 場次；少數列的 `type` 為空字串）
- `lose_reason`：出界、對手落地致勝、未過網、掛網、落點判斷失誤
- `win_reason`：對手出界、落地致勝、對手未過網、對手掛網、對手落點判斷失誤

## 重要慣例
- **A/B ↔ 姓名**：A=`matches.player_a`、B=`matches.player_b`。例：Axelsen vs Lee 該場 A=Viktor AXELSEN、B=LEE Zii Jia。
- **「某球種得分數」**：指該球即致勝球 → `type=... AND player=... AND win_reason IS NOT NULL`。
- **目前資料範圍**：`matches` 含 194 場（189 正式 + 5 NYCU 練習，2022–2024）；`rallies` 涵蓋 169 場、`shots` 涵蓋 **138 場**（其餘只有目錄資料：練習片、或該場沒有標註檔）。**查特定比賽務必用 `match_name` 篩**，否則會跨 138 場加總（這是最常見的錯誤來源）。
- **進階分析**：跑動距離、擊球高度、殺球回動速度等不在本 DB → 取 `analyze_match_id` 後改用 **badminton-analyze** skill。
- **影片片段**：標註多但實際影片少 → 一律 `has_video=1` 過濾再回給使用者。
