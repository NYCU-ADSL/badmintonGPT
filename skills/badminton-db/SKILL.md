---
name: badminton-db
description: >-
  查羽球賽事資料庫（選手有哪些比賽、逐拍統計如球種次數/得失分原因、比分、含特定戰術球種的
  回合片段）。當問題牽涉資料庫內既有賽事數據時，參考本 playbook 後呼叫 badminton-db MCP 工具。
---

# badminton-db playbook

資料庫存取一律透過 **badminton-db MCP** 的工具（不要自己跑 shell）：
- `list_tables()` → 看有哪些表
- `describe_table(table)` → 看某表欄位
- `query(sql)` → 跑**單句 SELECT**，回 `{rows, row_count}`（上限 200 列）

## 規則
1. 只下 **單句 SELECT**（多句、DELETE/UPDATE/INSERT 都會被拒）。
2. **回合影片片段**：一定要 `WHERE has_video=1`，只回實際有影片檔的 rally；資料庫逐拍標註很多，但實際有影片的回合很少。
3. 球種、得失分原因是**中文 enum**；選手用 `A`/`B`，姓名對照見 `matches.player_a/player_b`。完整欄位與 enum 見 `references/schema.md`。
4. 要生成精華影片時，傳給 reels 的 `match_name` 用 `matches.name`（已去 .mp4）。

## 常見查詢
```sql
-- 某選手有哪些比賽
SELECT name FROM matches WHERE name LIKE '%AXELSEN%';

-- 某選手某球種「得分數」(該球即致勝球)
SELECT COUNT(*) FROM shots WHERE type='殺球' AND player='A' AND win_reason IS NOT NULL;

-- 失分原因分布
SELECT lose_reason, COUNT(*) n FROM shots
WHERE lose_reason IS NOT NULL GROUP BY lose_reason ORDER BY n DESC;

-- 兩位選手某球種使用次數比較
SELECT player, COUNT(*) n FROM shots WHERE type='挑球' GROUP BY player;

-- 三局比分
SELECT set_no, MAX(score_a) a, MAX(score_b) b FROM rallies GROUP BY set_no ORDER BY set_no;

-- 哪些回合有影片片段（先列有檔的回合）
SELECT rally_id, video_filename FROM rallies WHERE has_video=1 ORDER BY rally_id;
```

> 提醒：
> - `rallies`/`shots` 用 **`match_name`**（= `matches.name`，不含 .mp4）當 key。逐拍涵蓋 **27 場正式賽事**，**查特定比賽務必** `WHERE match_name = '<matches.name>'`（否則跨 27 場加總）。先用 `matches` 的 `name LIKE` 找到要的 match_name。
> - rally_id 是 `set_scoreA_scoreB`（如 `1_05_04`），對應 `video_filename`。要把某球種對到實際影片，先用 `has_video=1` 取有檔的回合，再以 `set_no` + 比分對照 `shots`。
