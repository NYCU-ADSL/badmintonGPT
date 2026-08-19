---
name: badminton-analyze
description: >-
  單一羽球比賽的進階數據與戰術分析（跑動距離、擊球高度/過網高度、後場擊球數、失分空間分布、
  回合間休息時間、球種得分率、殺球後回動速度、統計宣稱驗證）。當使用者針對「某一場比賽」問這類
  進階指標時，依本 playbook 先用 badminton-db 取得該場的 analyze_match_id，再呼叫
  badminton-analyze MCP。計算邏輯全部封裝在 MCP 裡，絕對不可自行心算或編造數字。
---

# badminton-analyze 戰術與數據分析 playbook

remote MCP（CoachAI）。8 個**同步**工具，每個都吃 `match_id`（必填）+ `match_type`
（預設 `"single"`，目前資料都是單打）。因為是同步的，**不適用** long-mcp-job 的輪詢流程。

任何針對「單一比賽」的進階數據提問，順序固定：
**確認 match_id → 判斷分析意圖選工具 → 換上真實姓名、只呈現 summary**。

## 流程一：先拿到 `match_id`（不是比賽名稱！）

`match_id` 是 CoachAI 端的**數字 ID**，存在 badminton-db 的 `matches.analyze_match_id`。
**直接把資料夾名稱／比賽名稱丟進去一定失敗**（伺服器回 `Failed to fetch set data: 400`）。

```sql
-- 使用者只給選手/賽事名稱時，先問 badminton-db
SELECT name, player_a, player_b, tournament, round, year, analyze_match_id
FROM matches
WHERE name LIKE '%AXELSEN%' AND analyze_match_id IS NOT NULL
ORDER BY year DESC;
```
- 對話脈絡中已鎖定某一場且已有 `analyze_match_id` → 直接進流程二。
- 查到多場 → 先請使用者選一場（或依賽事/年份/輪次挑最相符的那場），**不要**把多場的數字混在一起。
- `analyze_match_id IS NULL`（例如 NYCU 練習片段）→ **這場無法做進階分析**，據實告知，
  改用 badminton-db 的逐拍統計；**絕不可以猜一個數字**。
- 順手把同一列的 `player_a` / `player_b` 記下來，流程三要用。

## 流程二：選對應的分析工具

| 使用者想知道的 | 工具 |
| :--- | :--- |
| 後場擊球數量 | `get_backcourt_count` |
| 擊球高度分布 / 過網高度 | `get_shot_height` |
| 失分空間分布 / 失誤位置 | `get_lost_point_distribution` |
| 回合間休息時間（秒） | `get_rally_rest_time` |
| 跑動距離（總距離／每回合／每拍平均） | `get_running_distance` |
| 球路得分率 / 各球種效益 | `get_shot_win_rate` |
| 殺球後的回動速度（回中線 center／發球線 service_line） | `get_smash_followup_speed` |
| 驗證某個統計宣稱 | `verify_match_statistics` |

參數：`{"match_id": "123", "match_type": "single"}`。
`verify_match_statistics` 另外必填 `metric`（如 `"shot_win_rate"`）與 `condition`
（如 `"highest"` / `"lowest"`）。

## 流程三：結果解析與呈現規則（重點）

回傳是 `{players, summary, details}`（部分工具沒有 `details`）。

1. **姓名一定要自己換**：MCP 的 `players` 永遠回字面上的 `"Player A"` / `"Player B"`，
   **不是**真實姓名。用流程一查到的 `matches.player_a` / `player_b` 替換
   （A/B 綁定與 badminton-db 一致，已實測對得上）。查不到姓名就寫 A/B，不要亂猜。
2. **優先輸出 summary**：只取 `summary` 的數字，轉成好讀的 Markdown 表格或條列。
3. **捨棄 details**：除非使用者明講「列出每回合細節」「看第幾拍」，否則**不要**把 `details`
   的長陣列印出來（動輒上百筆，會洗版）。
4. **數據為王**：`0` 或 `null` 就誠實呈現（某些比賽確實沒有該項標註），不要腦補、不要改寫。
5. 回傳若是 `{"error": ...}`，把原因說出來（通常是 `match_id` 不對），不要假裝有數字。

## 與其他工具的分工
- **一般逐拍統計 / 球種次數 / 比分 / 找比賽** → `badminton-db`（SQL，資料在本地）。
- **單場的進階指標（跑動、速度、空間分布、得分率）** → 本 skill。
- **生成精華影片** → badminton-reels；**檢索既有片段** → badminton-video-retrieval。

## 範例：「Axelsen 對 Lee Zii Jia 那場，殺球後的回動速度？」
```
-- 1) badminton-db
SELECT name, player_a, player_b, analyze_match_id FROM matches
WHERE name LIKE '%AXELSEN%LEE_Zii_Jia%' AND analyze_match_id IS NOT NULL;
→ Viktor_AXELSEN_LEE_Zii_Jia_EAST_VENTURES_Indonesia_Open_2022_Semifinals |
  Viktor AXELSEN | LEE Zii Jia | 123

-- 2) badminton-analyze
get_smash_followup_speed({"match_id": "123", "match_type": "single"})
→ players: {A: "Player A", B: "Player B"}   # ← 換成 Viktor AXELSEN / LEE Zii Jia
  summary: {A: {service_line: {…count: 0}, center: {average_speed: 0.87, max_speed: 1.55, count: 19}}, …}
```
> 以下是本場殺球後回動速度分析：
>
> | 選手 | 回動目標 | 平均速度 (m/s) | 最高速度 (m/s) | 次數 |
> | :--- | :--- | :--- | :--- | :--- |
> | Viktor AXELSEN | 中線 (center) | 0.87 | 1.55 | 19 |
> | Viktor AXELSEN | 發球線 (service_line) | 0.0 | 0.0 | 0 |
> | LEE Zii Jia | 中線 (center) | 0.67 | 0.95 | 10 |
> | LEE Zii Jia | 發球線 (service_line) | 0.0 | 0.0 | 0 |
>
> *註：已省略單一回合的細節數據 (details)。*
