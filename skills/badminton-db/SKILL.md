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
5. 進階指標（跑動距離、擊球高度、殺球回動速度、球種得分率…）**不在本 DB**：先在這裡查出該場的
   `analyze_match_id`，再依 **badminton-analyze** skill 呼叫那個 MCP。
4. 要生成精華影片時，傳給 reels 的 `match_name` 用 `matches.name`（已去 .mp4）。

## 常見查詢
```sql
-- 某選手有哪些比賽（順便帶出進階分析要用的 analyze_match_id）
SELECT name, tournament, round, year, analyze_match_id
FROM matches WHERE name LIKE '%AXELSEN%' ORDER BY year DESC;

-- 某選手某球種「得分數」(該球即致勝球)。⚠️ 沒有 match_name 就是 138 場的總和！
SELECT COUNT(*) FROM shots
WHERE match_name='Viktor_AXELSEN_LEE_Zii_Jia_EAST_VENTURES_Indonesia_Open_2022_Semifinals'
  AND type='殺球' AND player='A' AND win_reason IS NOT NULL;

-- 失分原因分布（單場：務必加 match_name；不加就是全庫統計）
SELECT lose_reason, COUNT(*) n FROM shots
WHERE match_name='<matches.name>' AND lose_reason IS NOT NULL GROUP BY lose_reason ORDER BY n DESC;

-- 兩位選手某球種使用次數比較（單場）
SELECT player, COUNT(*) n FROM shots WHERE match_name='<matches.name>' AND type='挑球' GROUP BY player;

-- 三局比分（單場）
SELECT set_no, MAX(score_a) a, MAX(score_b) b FROM rallies
WHERE match_name='<matches.name>' GROUP BY set_no ORDER BY set_no;

-- 哪些回合有影片片段（先列有檔的回合）
SELECT rally_id, video_filename FROM rallies
WHERE match_name='<matches.name>' AND has_video=1 ORDER BY rally_id;
```

> 提醒：
> - `rallies`/`shots` 用 **`match_name`**（= `matches.name`，不含 .mp4）當 key。`matches` 有 **194 場**
>   （2022–2024），其中 **138 場**有逐拍 `shots`、169 場有 `rallies`。**查特定比賽務必**
>   `WHERE match_name = '<matches.name>'`——少了它就會把 138 場加總（同名選手、同賽事不同年份的
>   場次很多，這是最容易答錯的地方）。先用 `matches` 的 `name LIKE` 找到要的 match_name；
>   同一組選手可能有多場，必要時用 `tournament` / `year` / `round` 再收斂。
> - rally_id 是 `set_scoreA_scoreB`（如 `1_05_04`），對應 `video_filename`。要把某球種對到實際影片，先用 `has_video=1` 取有檔的回合，再以 `set_no` + 比分對照 `shots`。
