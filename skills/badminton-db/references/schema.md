# badminton.db — schema 與 enum 對照卡

## 表結構（實際欄位）
```
matches(folder, name, tournament, round, player_a, player_b, year, is_practice)
  - folder      : HF 資料夾名（含 .mp4）
  - name        : 去 .mp4 的可讀名 = 傳給 reels 的 match_name
  - player_a/b  : 對應 shots.player 的 'A'/'B'（僅有逐拍資料的比賽才填；其餘為 NULL）
  - is_practice : 1=NYCU 練習片, 0=正式賽事
  - year        : 皆 2022

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
- `type`（球種）：放小球、挑球、擋小球、殺球、點扣、發短球、推球、切球、過度切球、勾球、長球、發長球、平球、撲球、後場抽平球、防守回抽、防守回挑、未知球種
- `lose_reason`：出界、對手落地致勝、未過網、掛網、落點判斷失誤
- `win_reason`：對手出界、落地致勝、對手未過網、對手掛網、對手落點判斷失誤

## 重要慣例
- **A/B ↔ 姓名**：A=`matches.player_a`、B=`matches.player_b`。例：Axelsen vs Lee 該場 A=Viktor AXELSEN、B=LEE Zii Jia。
- **「某球種得分數」**：指該球即致勝球 → `type=... AND player=... AND win_reason IS NOT NULL`。
- **目前資料範圍**：`matches` 含全 32 場（27 正式 + 5 NYCU 練習）；`rallies`/`shots` 涵蓋**全部 27 場正式賽事**（練習片無逐拍）。**查特定比賽務必用 `match_name` 篩**，否則會跨 27 場加總。
- **影片片段**：標註多但實際影片少 → 一律 `has_video=1` 過濾再回給使用者。
