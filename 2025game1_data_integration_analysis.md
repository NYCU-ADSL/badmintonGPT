# `2025game1_results.csv` 整合至 `data` 的欄位分析

## 1. 結論

`2025game1_results.csv` 可以轉成與
`data/Data/Akane_YAMAGUCHI_AN_Se_Young_BWF_World_Championships_2022_Semi_finals.mp4/label/set1.csv`
相同的 31 欄 CSV 外形，而且 rally、拍序、全域影格、球員 A/B、球種、勝負原因等核心欄位大多可以由現有資料直接轉換或規則化推導。比分鏈中有一個缺少的 rally，以及兩段來源彼此矛盾的區間；這些區間需人工或影片確認，不能宣稱全自動重建。

但目前無法只靠這份來源 CSV 完整還原所有標註。以下資訊沒有等價來源：

- `aroundhead`、`backhand`
- `hit_height`、`landing_height`
- `player_location_*`、`opponent_location_*`
- 每個 rally 最後一拍的精確 `landing_x/y/area`
- 每個 rally 最後一拍的精確 `end_frame_num`
- `flaw` 與 `db` 的原始定義值

這些欄位應留空或另設「未知」狀態，不能直接填 `0` 冒充「否」。其中站位、姿勢、高度與最後落點，需要原始比賽影片、球員/球體追蹤模型或人工標註才能補齊。

就目前專案的 `badminton-db` 匯入流程而言，時間、座標、高度、站位、`flaw`、`db` 並未寫入 shots 資料表，因此先完成核心欄位即可支援現有多數查詢。不過匯入器會把空白的 `aroundhead`、`backhand` 轉成 `False`，這會混淆「未知」和「否」；若要保留資料品質，應先讓資料模型支援 nullable boolean。

## 2. 實際資料盤點

| 項目 | 結果 |
|---|---:|
| 來源欄位數 | 23 |
| 來源資料列數 | 628 |
| 可歸屬正式局數的資料列 | 623 |
| 第一局 | 344 拍、38 rallies |
| 第二局 | 279 拍、35 rallies |
| 有逐拍標註的正式 rallies | 73 |
| 比分顯示的實際得分數 | 74（第一局 39 分、第二局 35 分） |
| 疑似賽後誤偵測 | 5 拍，即來源 rally 74 |
| 目標格式欄位數 | 31 |
| 來源球種種類 | 18 |
| 每個正式 rally 的 `end_reason` | 73/73 皆有 |
| `rally_winner` | 66/73 rallies 有值；7 個空值中有 6 個落在矛盾／缺 rally 區間 |
| 比分缺漏 | 16 拍，集中在 rallies 49、50、60；前後比分只能限制可能值，無法全部唯一決定 |
| `hit_area` | 623/623 正式資料列皆空 |

依來源的賽前比分、終局原因及場地上下半部對應，可重建：

- player A：`SUNG S.Y.`
- player B：`CHRISTOPHERSEN`
- 第一局：A 以 21–18 勝
- 第二局：A 以 21–14 勝
- 由比分變化和結束原因的多數一致性推定：第一局上半場是 A、下半場是 B；第二局交換場地，上半場是 B、下半場是 A。由於逐拍 `hitter` 本身有明顯抖動，此對應應當作局級規則，不應拿每列偵測值重新判斷。

來源 rally 74 的 `set`、比分與比分來源皆空，而且前一 rally 已使第二局達到 21–14，因此應視為賽後誤偵測，轉檔時排除。

另有三段必須人工覆核：

- rally 24 的賽前比分是 13–10，`end_reason` 顯示 A 得分；下一筆 rally 25 的賽前比分卻是 14–11。一次 rally 不可能讓雙方各加一分，且第一局 21–18 共 39 分、來源卻只有 38 個 rallies，表示兩者之間很可能漏了一個由 B 得分的 rally。
- rallies 48–50 前後比分由 6–3 變成 7–5，代表三分應分配為 A 一分、B 兩分；三筆 `end_reason` 依固定場地對應卻會得到 A 兩分、B 一分。
- rallies 59–60 前後比分由 11–9 變成 12–10，代表雙方各一分；兩筆 `end_reason` 卻都指向 A 得分。

這些矛盾可能來自 OCR 比分、結束原因 side 判斷，或漏偵測。沒有影片時只能保留衝突，不能任選一個來源當真值。

## 3. 目標 31 欄逐欄對照

狀態分成：

- **直接**：只需改欄名或格式。
- **可後處理**：可以由同一列、相鄰列或 rally 規則推導。
- **部分可做**：大多數列可推導，但最後一拍或定義仍需額外資訊。
- **不確定／缺少**：現有 CSV 無法可靠產生。

| 目標欄位 | 來源或產生方式 | 狀態 | 注意事項 |
|---|---|---|---|
| `rally` | `rally` | 可後處理但有缺口決策 | 第二局來源 39–73 可減 38，重編為 1–35。第一局在來源 rally 24、25 間疑似漏一分；影片確認前建議暫時保留來源 1–38，並在 QA 報告標示缺 rally，避免憑空插入無逐拍資料的列。 |
| `ball_round` | `ballround` | 直接 | 僅欄名不同。 |
| `time` | `hit_frame_global / FPS` | 可後處理 | 目標資料使用 `hh:mm:ss`。若原始影片確認為 30 FPS，可取 `floor(frame/30)`；未確認 FPS 前不能視為完全確定。 |
| `frame_num` | `hit_frame_global` | 直接 | 目標使用完整影片的全域影格，不應使用會在每個 rally 重設的 `hit_frame`。 |
| `end_frame_num` | 同 rally 下一拍的 `hit_frame_global` | 部分可做 | 非最後一拍可精確填入；最後一拍需 rally 結束影格、影片分析，或明確定義的估算規則。 |
| `roundscore_A` | `scoreA` 加上本 rally 結果 | 部分可做 | 來源是 rally 開始前比分，目標範例是 rally 結束後比分。一般列可依得分者加 1；rallies 24、48–50、59–60 有來源矛盾，需影片／人工確認。 |
| `roundscore_B` | `scoreB` 加上本 rally 結果 | 部分可做 | 同上。 |
| `player` | 前一 rally 得分者 + 拍序交替；`hitter` 作輔助 QA | 部分可做 | 下一 rally 的發球者應是前一 rally 得分者，再依 `ballround` 奇偶讓 A/B 交替。每局第一個 rally 和得分者衝突區間需用場地 side／影片定錨。來源有 56 次同一 rally 連續兩拍標成同一 side，不可逐列盲信 `hitter`。 |
| `server` | `ballround` 在 rally 中的位置 | 可後處理 | 目標的值其實是擊球狀態：第一拍 `1`、中間拍 `2`、死球拍 `3`；單拍 rally 應填 `3`。 |
| `type` | `shot_type` 經 18 類字典翻譯 | 可後處理 | 類別數和目標 18 類相符；部分英文名稱需確認來源模型的 ontology，見第 5 節。第一拍另有發球誤分類問題。 |
| `aroundhead` | 無 | 缺少 | 需姿勢模型或人工標註；空白不可直接解讀為 0。 |
| `backhand` | 無 | 缺少 | 需姿勢／持拍側判斷或人工標註；空白不可直接解讀為 0。 |
| `hit_height` | 無 | 缺少 | 此欄表示擊球點高於或低於網高，不能由平面落點座標可靠推回。 |
| `hit_area` | `hit_xy_court_x/y` 分區 | 可後處理但需規格 | 來源原欄 `hit_area` 全空；可用球場公尺座標依 CoachAI 1–14 區定義分箱。正式轉換前需固定邊界、方向翻轉及界外區規格。 |
| `hit_x` | `hit_xy_img_x` | 直接 | 都是目前這一拍的影像座標；可保留小數，若要仿目標格式再定義四捨五入規則。 |
| `hit_y` | `hit_xy_img_y` | 直接 | 同上。 |
| `landing_height` | 下一拍的 `hit_height`；最後一拍另行取得 | 缺少 | 目標資料中，同 rally 的 `landing_height[n] == hit_height[n+1]`；但來源連 `hit_height` 也沒有。 |
| `landing_area` | 下一拍的 `hit_area` | 部分可做 | 非最後一拍可由下一拍擊球區產生；最後一拍需球體追蹤／人工標註。 |
| `landing_x` | 下一拍的 `hit_xy_img_x` | 部分可做 | 非最後一拍可精確位移；目標範例 482/482 個同 rally 相鄰轉移皆符合 `landing_x[n] == hit_x[n+1]`。最後一拍缺少實際落點。 |
| `landing_y` | 下一拍的 `hit_xy_img_y` | 部分可做 | 同上；目標範例 482/482 個相鄰轉移皆一致。 |
| `lose_reason` | `end_reason` | 可後處理 | 僅填 rally 最後一列；映射見第 6 節。 |
| `win_reason` | `end_reason` | 可後處理 | 僅填 rally 最後一列；和 `lose_reason` 成對產生。 |
| `getpoint_player` | `rally_winner`、比分增量或 `end_reason` + side/A/B 對應 | 部分可做 | 66 個有 `rally_winner` 的 rallies 可轉換；rally 73 可由終局推定。rallies 24、48–50、59–60 的比分鏈和原因有衝突，應人工覆核。 |
| `flaw` | 無 | 缺少 | 建議留空，待人工 QA；不可預設為 0。 |
| `player_location_area` | 無 | 缺少 | 擊球座標不等於球員雙腳中心，不能拿 `hit_area` 代替。 |
| `player_location_x` | 無 | 缺少 | 需球員偵測與腳點投影。 |
| `player_location_y` | 無 | 缺少 | 需球員偵測與腳點投影。 |
| `opponent_location_area` | 無 | 缺少 | 需對手追蹤與球場分區。 |
| `opponent_location_x` | 無 | 缺少 | 需球員偵測與腳點投影。 |
| `opponent_location_y` | 無 | 缺少 | 需球員偵測與腳點投影。 |
| `db` | 無可靠對應 | 不確定 | 現有 `data/Data` 中可見 0、1、2 等值，但專案匯入器沒有使用此欄。需資料集維護者先定義其 provenance/version 語意；暫時留空比任意填 2 安全。 |

## 4. 可由我們後處理的內容

### 4.1 可確定自動化

1. 排除來源 rally 74 的 5 筆賽後誤偵測。
2. 依 `set` 拆成 `set1.csv` 與 `set2.csv`。
3. 第二局 rally 由 39–73 重編為 1–35。
4. `ballround` 改名為 `ball_round`。
5. `hit_frame_global` 填入 `frame_num`。
6. 非最後一拍的 `end_frame_num` 填下一拍 `hit_frame_global`。
7. 非最後一拍的 `landing_x/y` 填下一拍 `hit_xy_img_x/y`。
8. 依每個 rally 的結束原因產生 `lose_reason`、`win_reason`；對無衝突 rally 補 `getpoint_player`。
9. 對無衝突 rally 把賽前比分轉成賽後比分。
10. 對得分者已確定的區間，由前一 rally 得分者決定下一 rally 發球者，再以逐拍必定交替的規則產生 A/B；場地上下半部與原始 `hitter` 用於首個 rally 定錨及 QA。
11. 依拍在 rally 中的位置產生 `server=1/2/3`。
12. 用固定字典將 18 種英文球種轉為目標中文球種。

### 4.2 可做，但先確認規格或影片參數

- `time`：確認影片是 30 FPS 後即可由全域影格產生。
- `hit_area` 與非最後一拍 `landing_area`：需先取得 1–14 區的正式邊界與上下場方向規則，再由 `hit_xy_court_x/y` 產生。
- 第一拍的 `type`：來源共有 21 筆 `serve long/short`，其中只有 19 筆位於第一拍，另 2 筆錯位在第二拍；其餘第一拍被分成一般球種。可依「第一拍必為發球」強制改成發球類，但短發或長發仍需使用下一拍位置、軌跡或影片判斷。
- 最後一拍的 `end_frame_num`：可用固定延遲估算，但若目標是和人工標註一致，應由 rally 邊界或影片偵測取得。
- rallies 24、48–50、59–60 的得分者與賽後比分：先保留來源衝突，待影片或另一份正式計分資料裁決。

### 4.3 需要影片模型或人工標註

- `aroundhead`、`backhand`
- `hit_height`、`landing_height`
- 所有 `player_location_*`、`opponent_location_*`
- 每個 rally 最後一拍的精確落點與落點區
- `flaw`

## 5. 球種建議映射

來源剛好有 18 類，能和 CoachAI/ShuttleSet 的 18 類對齊。以下映射中，標為「高」者可直接套用；「中」者最好向產生 `2025game1_results.csv` 的模型文件確認英文類別定義。

| 來源 `shot_type` | 目標 `type` | 信心 | 備註 |
|---|---|---|---|
| `serve short` | 發短球 | 高 | 第一拍限定。 |
| `serve long` | 發長球 | 高 | 第一拍限定。 |
| `net pop` | 放小球 | 中 | 推測對應官方 `net shot`。 |
| `backstop` | 擋小球 | 中 | 推測對應官方 `return net`；名稱不是官方英文，需確認。 |
| `smash` | 殺球 | 高 | 直接對應。 |
| `overhead wrist shot` | 點扣 | 中高 | 對應 `wrist smash`。 |
| `net lift` | 挑球 | 高 | 對應 `lob`。 |
| `defensive pop` | 防守回挑 | 中高 | 對應 `defensive return lob`。 |
| `clear` | 長球 | 高 | 直接對應。 |
| `drive` | 平球 | 高 | 直接對應。 |
| `short flat` | 小平球 | 中高 | 對應 `driven flight`。 |
| `backcourt drive` | 後場抽平球 | 高 | 對應 `back-court drive`。 |
| `drop net` | 切球 | 中 | 推測對應 `drop`，名稱需確認。 |
| `passive shot` | 過渡切球 | 中 | 推測對應 `passive drop`。目標資料既有值寫作「過度切球」，官方文件寫作「過渡切球」，需先統一字詞。 |
| `push shot` | 推球 | 高 | 對應 `push`。 |
| `rush shot` | 撲球 | 高 | 對應 `rush`。 |
| `defensive drive` | 防守回抽 | 高 | 對應 `defensive return drive`。 |
| `cross-court net shot` | 勾球 | 高 | 直接對應。 |

來源 `shot_type_conf` 的中位數為 0.9585、平均為 0.9277；623 筆正式資料中有 49 筆低於 0.8、120 筆低於 0.9。建議把原始信心值保存在轉換 sidecar 或 QA 報告中，即使目標 31 欄沒有容納它。

## 6. rally 結束原因映射

| 來源 `end_reason` 型態 | `lose_reason` | `win_reason` | 得分者 |
|---|---|---|---|
| `<loser> player's shot goes out of bounds` | 出界 | 對手出界 | 非 `<loser>` |
| `<loser> player's shot hit the net` | 掛網 | 對手掛網 | 非 `<loser>` |
| `<loser> player fails to return the shuttle over the net` | 未過網 | 對手未過網 | 非 `<loser>` |
| `<winner> player hits a winner` | 對手落地致勝 | 落地致勝 | `<winner>` |

來源的 73 個正式 rallies 都有 `end_reason`，所以可完整產生原因文字；但不能因此認定所有得分者都能可靠重建。`rally_winner` 空值所在的 rallies 24、48–50、59–60 與前後比分存在衝突，只有 rally 73 可由 20–14 的終局和比賽結束明確推為 A 得分。`end_reason_source`（`court` 或 `courttcn`）應保留在 QA sidecar，方便追查自動判斷來源。

## 7. 來源中直接相符、額外與空缺欄位

### 7.1 直接相符或只需改名

| 來源 | 目標 |
|---|---|
| `rally` | `rally`，但第二局需局內重編 |
| `ballround` | `ball_round` |
| `hit_frame_global` | `frame_num` |
| `hit_xy_img_x/y` | `hit_x/y` |
| `scoreA/B` | `roundscore_A/B`，但需轉成賽後比分；衝突區間不可直接補 |
| `rally_winner` | `getpoint_player`，需 side→A/B；已有值的 66 個 rallies 可用 |

### 7.2 來源多出的欄位

這些不在目標 31 欄中，但有些值得保留成 sidecar，例如 `2025game1_conversion_provenance.csv`：

| 來源欄位 | 建議 |
|---|---|
| `game_name` | `game1` 太泛用；可留 provenance，不足以命名正式資料夾。 |
| `set` | 用來拆分 `set1.csv`、`set2.csv`，輸出後不需留在列內。 |
| `hit_frame` | rally clip 內的局部影格；可供核對，目標使用全域影格。 |
| `shot_type_conf` | 強烈建議保留作 QA。 |
| `hit_xy_court_x/y` | 強烈建議保留，可用來計算 area，且比像素座標更可跨影片比較。 |
| `end_reason_raw` | 全空，可不保留。 |
| `end_reason_source` | 建議保留作 QA。 |
| `playerA`、`playerB` | 應提升為比賽 metadata；目標逐拍 CSV 只記 A/B。 |
| `score_source` | 建議保留作 QA，尤其 `ocr`、`chain`、`set-only` 的可信度不同。 |

`hit_area` 雖與目標同名，但來源 623 筆正式列全部為空，實際上屬於缺失欄位，不算直接相符。

### 7.3 目標缺少來源資料的欄位

- 完全缺少：`aroundhead`、`backhand`、`hit_height`、`landing_height`、`flaw`、六個球員/對手位置欄位、`db`。
- 最後一拍缺少：`end_frame_num`、`landing_area`、`landing_x`、`landing_y`。
- 定義需確認：`time` 的 FPS、area 的分區邊界、第一拍發球的短／長分類。

## 8. 目前資料中的風險與 QA 規則

1. **`hitter` 不能逐列直接使用。** 正式資料中有 56 個同 rally 相鄰拍被標成同一個 `top` 或 `bottom`；單打的合法擊球者應交替。得分者已知時，可由前一 rally 得分者決定發球者，再依 `ballround` 奇偶產生後續球員，並把原始 side 衝突列入 QA。每局首個 rally 與得分衝突區間需以場地 side 或影片定錨。
2. **第一拍球種不可靠。** 73 個正式 rallies 中只有 19 個第一拍被標成發球，另有 2 個發球標籤錯位在第二拍。第一拍應強制歸入發球類，再判斷短／長發。
3. **比分語意不同。** 來源是賽前比分，目標是該 rally 結束後比分。若直接複製，所有列都會落後一分。
4. **比分鏈不是完全連續。** rallies 24→25 顯示雙方各加一分，代表漏 rally 或來源錯誤；rallies 48–50、59–60 的比分總增量和 `end_reason` 也不一致。這些列需人工覆核。
5. **座標的列語意需位移。** 來源 `hit_xy_img` 是該拍擊球點；目標 `landing_*` 是該拍的目的點。非最後一拍的目的點等於下一拍擊球點。
6. **不可把擊球點當球員站位。** 擊球點可離腳點很遠，尤其撲球、跳殺與跨步救球。
7. **來源信心值應留存。** 49 筆球種信心低於 0.8，適合優先人工抽查。
8. **最後一拍需特別處理。** 下一拍不存在，不能用 shift 方式生成落點與結束影格。
9. **未知布林值不可默認為否。** 目前匯入器會把空白 `aroundhead`/`backhand` 轉為 false；若統計會使用這兩欄，應先修 schema。

建議轉換後至少執行以下驗證：

- 第二局 rally 從 1 連續遞增；第一局在確認漏 rally 的處理策略後，檢查符合所選規則。
- 每個 rally 的 `ball_round` 從 1 連續遞增。
- 每個 rally 的 A/B 嚴格交替。
- 除最後一拍外，`end_frame_num[n] == frame_num[n+1]`。
- 除最後一拍外，`landing_x/y[n] == hit_x/y[n+1]`。
- 每個 rally 只有最後一拍有 `lose_reason`、`win_reason`、`getpoint_player`。
- 同一 rally 所有列的賽後比分一致。
- 第一局終局為 21–18、第二局終局為 21–14。
- 不輸出來源 rally 74。
- QA 報告必須列出 rallies 24、48–50、59–60 的比分／原因衝突，直到人工裁決。

## 9. 建議整合順序

### 階段 A：先產生可用的核心 CSV

- 產生完整 31 欄表頭。
- 自動填入確定欄位與可規則推導欄位。
- 無法可靠取得的欄位留空。
- 衝突區間不靜默猜值；另列 `needs_review`，由人工或影片結果覆寫。
- 另外輸出 provenance/QA sidecar，保留信心值、原始 side、court 座標、推導方式與警告。
- 先讓目前 `badminton-db` 可匯入並驗證比分、球種、勝負原因查詢。

### 階段 B：補 area 與最後一拍

- 確認 CoachAI 1–14 區邊界後，由 court 座標產生 `hit_area` 與非最後一拍 `landing_area`。
- 使用原始影片／TrackNet 類模型補每個 rally 最後一拍落點及結束影格。
- 核對所有第一拍是短發或長發。

### 階段 C：補完整姿勢與站位標註

- 球員偵測、追蹤、腳點投影。
- 正反手與繞頭姿勢分類。
- 擊球高度分類。
- 人工抽查低信心球種與模型衝突列。

## 10. 整合到 `data` 仍缺的比賽層級資訊

即使逐拍 CSV 已轉好，要建立和現有 `data/Data/<match>.mp4/` 一致的資料夾，仍需確認：

- 原始完整影片或可對應 `hit_frame_global` 的影片版本
- 正式球員全名與拼字（目前只有 `SUNG S.Y.`、`CHRISTOPHERSEN`）
- 賽事名稱、輪次及影片檔名
- 影片 FPS
- 是否要建立 `RallySeg.csv`；若需要，rally 起訖影格目前只能由擊球影格近似，無法等同人工 rally 邊界

在這些 metadata 確認前，可以完成轉換程式與暫存 `set1.csv`、`set2.csv`，但不宜自行猜測最終 match folder 名稱。

## 11. 參考定義

- CoachAI/ShuttleSet 官方欄位與 18 類球種對照：<https://github.com/wywyWang/CoachAI-Projects/tree/main/ShuttleSet>
- 類似 S² 標註格式對 `server`、`hit_height`、比分與影格的說明：<https://github.com/HuangYuHsien/S2DoublesDataset>
- 本專案實際匯入欄位：`mcps/badminton-db/ingest.py` 與 `mcps/badminton-db/ingest_lib/models.py`
