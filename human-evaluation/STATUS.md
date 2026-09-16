# 實作狀態

更新時間：2026-09-16（Asia/Taipei）。

## 目前網站：呈現需求 5 題預覽

資料集 `preview-5-presentation-v1`，seed `20260916`，5／5 題完成，三階段模型 `gpt-5.6-luna`。Function 數量為 2、1、2、3、1；呈現為文字、影片、影片、互動視覺化、比較圖表。問題預先檢查通過，intention 及 query prompt 都收到相同呈現要求。回答耗時依序 103.42、385.26、292.32、206.34、151.75 秒。

第 4、5 題均自行讀取 `skills/visualise/SKILL.md` 並產生圖表。已驗證第 4 題的賽事、場區與組合篩選，以及第 5 題的選手、比賽篩選會更新圖表。沒有對 BadmintonGPT 的回答流程或輸出做修改。

- 第 4、5 題都自行讀取 visualise 技能並產生 visualizer 區塊；瀏覽器已驗證圖表載入及各個篩選器能更新內容。
- 第 2 題第一次影片工作因比賽名稱無法載入而失敗，BadmintonGPT 自行改用實際比賽重新製作，最終影片約 96.47 秒，素材來自單場比賽。
- 第 3 題回覆包含兩支影片網址；第一支約 4.7 秒可載入，第二支在瀏覽器遭 net::ERR_BLOCKED_BY_ORB 阻擋，原生元件改以連結顯示。第二個例子描述的是回合後段的挑球，並非直接接發球。
- 第 4 題收到兩段原始輸出：5842 字元的分析與互動圖表，以及 225 字元與馬琳影片搜尋有關的附加內容。全部原樣保存。原服務歷史回放與即時輸出不一致，未用歷史回放刪減回答。
- 五題原始 query、收到的 WebSocket frames 與保存回答核對通過。Q1 評分門檻、評分保存與重新載入、手機頁面、兩個圖表互動檢查通過；臨時測試評分已移除。
- 以上驗證輸出保存與顯示行為，不代表回答中的統計、戰術或影片內容正確性已通過人工評估。

完整問答：`data/preview-5-presentation-v1/preview.md`。證據位於 `runtime/preview-5-presentation-v1/`：`question-review.json`、`output-verification.json`、`live-verification/`、`visual-interaction-check.json`、兩張圖表截圖及 `q003-browser-media.json`。直接 Python HTTP 探測兩網址均收到 403，不能用以判定影片可用性；瀏覽器實際載入紀錄為準。

## 最新修正：獨立呈現需求

新增 `presentation_sampling: compatible-presentation-v1`。分析主功能等機率選文字、比較圖表、互動視覺化；失分分布與後場站位另可選球場圖。影片搜尋與製作主功能保留影片需求。每題保存 `presentation`，並將對應需求同時傳入 intention 與雙語 query 生成；比較對象及互動控制依原提問範圍選擇，不虛構座標或量測軌跡。`visualise` 仍為技能背景，不計入 MCP function 數量。

抽樣使用獨立 seed，function 的 Poisson(1)+1、資料背景及 BadmintonGPT 原始回答流程維持原樣。manifest 保存新政策並阻止混用舊資料續跑，預設新資料集為 `preview-10-presentation-v1`。20 個相關測試通過，涵蓋格式相容性、選項覆蓋、可重現抽樣、政策隔離與原始輸出保存。

規則實作時先做離線抽樣檢查，後續五題試跑結果見上方。seed 20260916 的前五題預定呈現依序為文字、影片、影片、互動視覺化、比較圖表；報告在 `runtime/presentation-v1-check.json`。短批次不保證每種格式都出現，題目要求也不代表回答一定產生圖表。先前網站使用 `preview-5-scopes-v2`，現已更新為上方新資料集。

## 前一版修正：完整背景與多種提問範圍

移除資料類別抽樣與遮蔽；每題提供 match/rally/shots 及目標選手的相關比賽、年份、可用球種與資料範圍。六種範圍循環為選手年度、選手球種、戰術影片、跨賽事、選手比較、單場；function 抽樣維持 Poisson(1)+1。範圍決定問題主題，代表回合不再強制成為 query 的對象。

18 個相關測試通過，涵蓋完整背景保留、年度與跨賽事資料依據、選手大小寫、缺姓名紀錄排除、唯讀及可重現、目標選手／年份檢查、拒絕缺漏資訊引用、草稿修訂版本留存。資料政策 `full-context-scopes-v2`。

第一次草稿 `preview-5-scopes-v1` 出現模型自行替換選手的問題，僅生成問題且未送任何 query 給 BadmintonGPT，已停止並保留。修正後將 focus 選手／年份傳入 intention，新增送出前檢查；新試跑資料集為 `preview-5-scopes-v2`。第 4 題草稿混入外語字詞，已在送出前修正，原稿與原因留存；五題均通過檢查並完成回答。

## 前一批：完整背景與提問範圍 5 題預覽（保留）

資料集 `preview-5-scopes-v2`，seed `20260916`，5／5 題完成。三階段均使用 `gpt-5.6-luna`，function 數量為 2、1、2、3、1；每題完整提供三類背景。目標依序為：許玟琪 2023 年移動表現、李梓嘉球種教學、馬琳網前壓迫戰術、許玟琪跨賽事失分模式、安賽龍與金廷 2022 年球種比較。各題背景的相關比賽數為 24、3、16、24、6。

五題均取得實質回答，沒有停在補充 match ID 的要求。第 2 題影片第一次工作在語音合成階段失敗，BadmintonGPT 自行改用另一場比賽並完成影片；評測端未控制重試。回答耗時約 78、562、117、107、49 秒。

5／5 題通過原始 query、WebSocket 輸出與原 WebUI 歷史核對。另確認提問範圍、完整背景與實際問題生成 prompt 一致。報告：`runtime/preview-5-scopes-v2/output-verification.json`；完整預覽：`data/preview-5-scopes-v2/preview.md`。這些核對驗證原樣保存，不代表回答統計或戰術推論的正確性已通過人工評估。

公開網站檢查通過：5 題雙語問題與原始回答、4 個表格、影片中繼資料載入（約 75.4 秒）、評分保存與重新載入、手機顯示；無未捕捉瀏覽器錯誤。報告及截圖：`runtime/preview-5-scopes-v2/live-verification/`。臨時測試評分已依精確資料集及評測代碼移除。

## 前一版修正：資料類別採 Poisson + 1

資料類別數改為 `min(Poisson(λ=1) + 1, 3)`，每題提供 1–3 類；機率約為 36.8%、36.8%、26.4%。資料政策更新為 `optional-data-poisson-plus-one-v2`，manifest 的 offset 改為 1。Function 抽樣與 BadmintonGPT 回答流程維持原樣。

17 個相關測試通過，包含至少一類、分布、三類上限、七種非空子集合與舊資料政策隔離。尚未重新生成題目；網站保留現有 v3 題庫。

## 前一版資料規則：0–3 類可選背景

依使用者要求，出題背景類別數改為 `min(Poisson(λ=1), 3)`，從 `match`、`rally`、`shots` 隨機選取不重複類別。0 類時不抽資料庫，僅由 intention 出題；其他情況保留完整來源作稽核，但只將選取類別交給 query 生成模型，並移除指向未選取比賽／回合背景的關聯欄位。模型不必逐項使用提供的背景，也不能補造省略的資料。function 的 `Poisson(1) + 1` 抽樣維持不變。

資料政策為 `optional-data-poisson-v1`，與 intention 政策分開記錄。17 個生成與原始輸出保存相關測試通過，涵蓋 0–3 類分布、所有八種子集合、0 類不存取資料庫、跨類別欄位隔離、稽核來源保留、可重現抽樣及版本隔離。已依此規則完成下列新 5 題。

## 前一批：可選背景 5 題預覽（保留）

資料集 `preview-5-intents-v3`，seed `20260916`，5／5 題完成，三個生成階段均使用 `gpt-5.6-luna`。Function 數量為 2、1、2、3、1；背景依序為 shots、無、match＋rally、無、無。已核對選取結果可由 seed 重現、實際出題 prompt 只包含對應 `query_data`。

5 題原始 query、WebSocket 輸出及原 WebUI 歷史 API 核對全部通過。報告：`runtime/preview-5-intents-v3/output-verification.json`；完整意圖、雙語問題及回答：`data/preview-5-intents-v3/preview.md`。舊題庫與評分均保留。

本批第 1、2、4、5 題收到要求補充比賽名稱或 ID 的回答；未追問或補送資料。第 3 題完成接發球影片搜尋，耗時約 2 分 23 秒。品質觀察：第 1 題引用 available shot sequence 卻未在 query 列出序列；第 3 題英文 quarter-final 與繁中四強不一致。這些原始內容保留供人工評測。

公開網站瀏覽器檢查通過：5 題雙語問題與原始回答、第 3 題四支影片中繼資料載入、評分保存與重新載入、手機顯示，沒有未捕捉瀏覽器錯誤。報告及截圖：`runtime/preview-5-intents-v3/live-verification/`；臨時驗證評分已依精確資料集及評測代碼清除。

## 最新生成規則：Poisson 數量與主功能輪替

規則版本為 `user-capabilities-poisson-v2`。每題數量改為 `Poisson(λ=1) + 1`，只以可用意圖工具數（目前 10）為上限；移除原本均勻抽 1–5 個的方式。主功能依 seed 洗牌，每輪 10 題覆蓋全部功能，再隨機選其餘輔助功能。原始抽樣數量及主功能均保存，可重現單題抽樣。

依使用者修正，已移除強制英文作答的出題提示及 `requested_answer_language` 設定，題目維持自然措辭。送出端與回答處理不變；無論原服務用何種語言回答，都原樣保存，不翻譯、不因語言重跑。

生成提示以主功能為中心，近期意圖僅用於避免重複，其他抽中功能不必硬湊進題目。角色改為措辭風格，不再預先要求比較、訓練或精華影片；繁中問題也明確要求避免混入無關外語。

13 個生成與原始輸出保存相關測試通過。十萬次離線抽樣平均 2.00561 個，主功能覆蓋、續跑抽樣一致性、工具池上限及版本隔離均通過；報告 `runtime/poisson-v2-check.json`。已依此版本完成下列新 5 題。

## 前一批：Poisson 規則 5 題預覽（保留）

資料集 `preview-5-intents-v2`，seed `20260916`，5／5 題完成，三個生成階段均使用 `gpt-5.6-luna`。每題 function 數量為 2、1、2、3、1，與固定 seed 的抽樣結果一致，五題的主功能不同。

主題依序為：殺球後回位效率、網前球教學精華、防守轉攻影片、失分場區及戰術調整、核實最長回合間休息。問題未加入英文作答要求；第 1 題回答以英文為主，第 2–5 題以中文為主，內容均原樣保存。第 2、3 題分別花約 5 分 7 秒、7 分 36 秒完成回答，影片搜尋與製作由 BadmintonGPT 自行決定。

5 題原始 query、WebSocket 輸出及原 WebUI 歷史 API 核對全部通過。報告：`runtime/preview-5-intents-v2/output-verification.json`；逐題意圖、雙語問題與完整回答：`data/preview-5-intents-v2/preview.md`。所有舊題庫與評分保留。

公開網站瀏覽器檢查通過：5 題雙語問題與回答、2 個表格、2 支影片中繼資料載入（約 68.2 秒及 30.2 秒）、評分保存與重新載入、手機寬度，沒有未捕捉瀏覽器錯誤。報告與截圖：`runtime/preview-5-intents-v2/live-verification/`；臨時驗證評分已依精確資料集及評測代碼清除。

## 前一版修正：排除輔助工具

已將意圖抽樣池縮限為 8 個分析功能、影片搜尋及精華生成，共 10 個；完整 MCP 工具定義仍保留。資料庫、狀態／結果查詢、等待、健康檢查及 collection 探索不再作為意圖抽樣來源，提示也明確要求描述使用者需求。抽樣時提供工具定義，避免只看函式名稱誤解功能。

此修正只影響評測問題生成，不修改 BadmintonGPT 的回答流程或工具。新規則版本為 `user-capabilities-v1`；舊資料集不能混入新規則續跑。原 10 題、回答及評分未變動。

已用既有 20 個工具的定義確認抽樣池為 10 個；19 個 Python 測試通過，包含輔助工具排除、原始工具池保留及不同規則版本禁止混合續跑。完整測試在沙箱內的 TestClient 處停住，移至沙箱外後正常通過。

## 前一批：排除輔助工具的 5 題預覽（保留）

資料集 `preview-5-intents-v1`，seed `20260916`，5／5 題完成。三個生成階段都使用 `gpt-5.6-luna`，每題從 10 個需求功能抽取 1–5 個（本批數量為 1、1、5、4、5）。第 2、3 題由 BadmintonGPT 自行製作影片，回答耗時約 6 分 22 秒、5 分 25 秒，評測端未控制其工具與 anchor 行為。

5 題原始請求、WebSocket 輸出及原 WebUI 歷史 API 核對全部通過。報告：`runtime/preview-5-intents-v1/output-verification.json`；完整題目與意圖：`data/preview-5-intents-v1/preview.md`。

公開網站瀏覽器檢查通過：5 題雙語問題、Q1 回答顯示規則、4 個表格、2 支影片中繼資料載入（約 35.5 秒及 22.2 秒）、評分保存與重新載入、手機寬度，無未捕捉瀏覽器錯誤。報告與截圖：`runtime/preview-5-intents-v1/live-verification/`。臨時驗證評分已依精確 dataset ID 與評測代碼清除。

出題品質觀察：第 2 題繁中混入外語詞 `göster`；5 題都涉及殺球後回位，題材多樣性仍有限。原生成內容保留供評測，沒有為了改善品質重抽或改寫回答。

回答語言觀察：第 2、3 題原始回答為中文，其餘以英文為主。已確認每題實際送出的 content 與保存的英文 query 一致，沒有傳送 locale。專案 `nanobot/workspace/SOUL.md` 指定預設英文，但上述兩題沒有遵循；未確認造成切換語言的具體原因。

## 前一批：10 題真實預覽（保留）

公開網站：https://virtual-infectious-notes-faculty.trycloudflare.com

本機網站：http://127.0.0.1:8810

前一批題庫：`data/preview-10-blackbox/dataset.json`，10／10 題完成，資料及評分留存；目前公開網站已切換為上述新 5 題。每題有英文／繁中問題及 BadmintonGPT 實際輸出；意圖、問題生成與 gateway 回答階段均使用 `gpt-5.6-luna`。尚未生成 300 題。

## 回答流程的界線

- 每題開啟既有 BadmintonGPT 的新 WebSocket 對話，只送一則英文 query。
- 不建立或修改回答用 AgentLoop，不攔截工具、不快取工具結果、不控制工具重試或 reels 工作，不補提示、不改寫回答。
- 已移除自動加入禁用 anchor 的條件。anchor 是否可用、等待與降級都由原服務處理。
- 評測端保存 `request.json`、逐筆原始 `output-frames.jsonl` 與依原生串流協定組合的 `output.json`。網站逐段呈現收到的文字，不裁切成最後一段摘要。
- 第 6 題曾等候約 26 分鐘後由原服務完成影片。另以原生 `attach` 訂閱同一個對話作為接收備援，沒有再送 query 或更動回答程序。

舊 `data/preview-10/` 曾使用工具攔截，不作為有效評測資料，已從網站撤下並留存備查。新舊題庫與評分透過 dataset ID 分開。

## 驗證結果

- 20 個 MCP 工具完成探索；每題抽樣 1–5 個工具；10 個英文問題無重複。
- 10／10 題核對通過：送出的 query 與題目完全相同、原服務每題只收到一則 query、保存文字逐字符合原始 WebSocket 輸出。
- 前一批核對報告：`runtime/preview-10-blackbox/output-verification.json`。
- 公開網站 10 題全部通過：雙語問題、Q1 顯示規則、回答渲染、評分保存及重新載入、手機版，無瀏覽器未捕捉錯誤。
- 真實回答共渲染 21 個表格、1 個視覺化、2 支影片。兩支影片均成功載入中繼資料，長度約 60 秒；第 6 題另完成實際播放檢查。
- 前一批公開網站報告與截圖：`runtime/preview-10-blackbox/live-verification/`；驗證用評分已移除。
- 前端建置、16 個 Python 測試、3 個 React 測試及 Chromium 端到端測試通過。長網址造成的手機超寬已在評測頁 CSS 修正。
- 生成容器正常結束，網站健康檢查通過，Cloudflare Quick Tunnel 持續執行。

## 原服務歷史紀錄差異

第 10 題的 WebSocket 傳回完整圖表回答（9,548 字元）與結尾摘要（262 字元）兩段，評測完整保存。原 WebUI 的歷史 API 卻只回傳結尾摘要，因此此題的「歷史 API 對照」不同，但「原始 WebSocket 對照」完全一致。其餘 9 題也與歷史 API 一致。未修改原服務來處理此差異；原始證據保存在 `runtime/native-q010-comparison.json` 與該題的 frame 紀錄。

## 舊診斷紀錄

修正評測界線前曾對主播連線做單次重試，並將本次被 reels 重啟中斷的舊工作標記為 failed。原始狀態及操作證據保存在 `runtime/anchor-retry/` 與 `runtime/reels-recovery/`，相關腳本已移至 `runtime/legacy-administration/`，不屬於新生成流程。
