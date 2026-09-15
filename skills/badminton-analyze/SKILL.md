---
name: badminton-analyze
description: >-
  使用 badminton-analyze MCP 工具分析羽球單打比賽。當使用者提供 match_id，
  並要求球種成效、失分落點、回合休息時間、跑動距離、後場使用、擊球高度、
  殺球後移動或數據驗證時使用。
---

# 羽球單打比賽分析

根據 MCP Server 回傳的比賽資料產生可核對的戰術分析。現在的正式分析範圍以單打為主，呼叫工具時使用：

```json
{
  "match_id": "200",
  "match_type": "single"
}
```

## 開始分析前

- 使用者已提供 `match_id` 時直接使用，不要再次詢問。
- 缺少 `match_id` 時，先請使用者提供。
- `match_id` 保持字串形式，不要猜測或自行替換。
- 除非使用者明確要求其他範圍，`match_type` 一律使用 `"single"`。
- 工具回傳 `error` 時，不要補造數值；說明失敗原因及缺少的資料。

## 可用工具

| MCP tool | 用途 |
| --- | --- |
| `get_backcourt_count` | 計算每位球員在後場擊球的次數及相關 rally 明細 |
| `get_shot_height` | 統計每位球員高於與低於網高的擊球次數 |
| `get_lost_point_distribution` | 統計每位球員在 1–16 區的失分分布 |
| `get_rally_rest_time` | 計算同一局相鄰 rallies 之間的休息秒數 |
| `get_running_distance` | 計算總跑動距離、每 rally 平均距離與每球平均距離 |
| `get_shot_win_rate` | 計算各球種的 attempts、winners 與 win_rate |
| `get_smash_followup_speed` | 計算殺球後往發球線或中心區域移動的速度 |
| `verify_match_statistics` | 從原始比賽資料重新計算並驗證最高或最低的統計結果 |

以上是 MCP 對外公開的名稱。不要使用 `register_*_tools`；那些是 Python 內部註冊函式。

## 工具選擇

使用者指定分析項目時，只呼叫相關工具。使用者要求完整比賽分析時，呼叫前七個分析工具，並依下方規則使用 `verify_match_statistics` 核對重要的極值結論。

### 球種致勝率

呼叫：

```json
{
  "match_id": "200",
  "match_type": "single"
}
```

使用 `get_shot_win_rate` 的：

- `players`：A、B 與實際球員姓名的對照。
- `summary`：依球員及球種列出 `attempts`、`winners`、`win_rate`。
- `data_quality`：總 rally、有效 rally、總球數、有效球數及略過數量。

`win_rate` 是 0–1 的比例。向使用者呈現時可以轉成百分比，但保留原始 attempts 和 winners，避免只比較小樣本比例。

### 失分區域分布

`get_lost_point_distribution` 回傳：

- `summary`：每位球員在各區域的失分比例。
- `details`：各 rally 的 `lose zone`。
- `data_quality`：有效與略過的 rally 數量。

區域代碼的合法範圍是字串 `"1"` 到 `"16"`。沒有完整區域對照資料時保留數字代碼，不要自行創造區域名稱。

### Rally 休息時間

`get_rally_rest_time` 的時間單位是秒。摘要包含：

- `average_rest_time`
- `max_rest_time`
- `min_rest_time`

`details` 包含相鄰 rally 的 `rally` 與 `rest_time`；`data_quality.rest_intervals` 表示實際建立的休息區間數。

### 其他動作與移動指標

- 後場次數使用 `get_backcourt_count`。
- 擊球高度使用 `get_shot_height`。
- 跑動距離使用 `get_running_distance`，距離以工具回傳單位為準，報告中清楚標示。
- 殺球後移動使用 `get_smash_followup_speed`，速度單位為 m/s。

## 驗證數值結論

當報告要聲稱某項統計是「最高」或「最低」時，用 `verify_match_statistics` 驗證。它目前支援單打及以下三種 metric：

| metric | 驗證內容 |
| --- | --- |
| `shot_win_rate` | 球員與球種的最高或最低致勝率 |
| `lost_point_distribution` | 球員與區域的最高或最低失分比例 |
| `rally_rest_time` | 最長或最短 rally 休息時間 |

呼叫範例：

```json
{
  "match_id": "200",
  "match_type": "single",
  "metric": "shot_win_rate",
  "condition": "highest"
}
```

`condition` 只能是 `"highest"` 或 `"lowest"`。驗證結果的 `summary` 會包含 `metric`、`condition` 與該 metric 對應的欄位：

- `shot_win_rate`：`player`、`shot_type`、`attempts`、`winners`、`win_rate`。
- `lost_point_distribution`：`player`、`zone`、`lost_points`、`total_lost_points`、`rate`。
- `rally_rest_time`：`set`、`rally`、`rest_time`。

若來源工具與驗證工具結果不同，以 `verify_match_statistics` 的重新計算結果為準，並指出兩者不一致，不要隱藏差異。

## 解讀資料品質

正式統計工具可能回傳 `data_quality`。分析時：

- 說明 `verified_rallies`、`valid_shots` 或 `rest_intervals` 等有效樣本數。
- `skipped_rallies` 或 `skipped_shots` 大於 0 時，提醒結論只涵蓋可驗證資料。
- 數值 `0` 代表已計算且結果為零；`null`、缺少欄位或 `error` 代表無法取得或計算，兩者不可混用。
- 不要從缺少的 details 推論球員表現。

## 回覆方式

先用 `players` 將 A、B 換成實際姓名，再整理重點：

1. 先回答使用者指定的問題。
2. 用少量關鍵數字支持結論，附上次數、比例及單位。
3. 比較球員時使用相同指標與相同資料範圍。
4. details 很長時只摘錄支持結論的 rally，不要完整傾倒原始 JSON。
5. 清楚區分工具直接回傳的結果與根據結果做出的戰術解讀。
6. 對 `verify_match_statistics` 支援的三種 metric，任何「最高」或「最低」的正式結論都應附上驗證結果；其他指標則附上來源工具的數值與有效樣本。