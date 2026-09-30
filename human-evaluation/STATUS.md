# 實作狀態

更新時間：2026-09-18（Asia/Taipei）。

## 正式版 200 題：已部署

`formal-200-v1`（count 200、seed 2026091701、模型 gpt-5.6-luna）已完成 200／200 題，generator exit code 0。200 題 query、locale、原始 WebSocket frame 與保存的 output_messages 均核對通過；本次部署前再次逐題核對 request/output JSON 一致。各主能力 16–17 題，資料庫 16 題、web 17 題、其他能力 167 題。

q086 保留原生回答的中文球種標籤 `小平球`（3 字）。q091、q149、q151、q176 與原 WebUI 歷史的分段不同，但收到的原始 frame 與保存回答一致；未為迎合語言或內容要求改寫、刪節或重送回答。完成／核對報告位於 `runtime/formal-200-v1/`。

2026-09-18 公開站已確認使用正式 200 題；本次播放器修復再次重建 web 並驗證線上輸出。先前 Docker 自動審核容量不足已解除。原題庫、原始問答與評分保留，200 題公開 query／answer／output_messages 與本機保存內容逐一一致。部署前檢查與資料 hash 位於 `runtime/formal-200-v1/deployment/`。

## Retrieval 影片播放修復（2026-09-18）

實測 q003、q104 的原始影片 URL 回傳 404；保留原始回答／連結並顯示失敗提示、重試及開啟原始影片。q126 原檔為 MPEG-4 Part 2 (`mp4v`)，Chromium 無法解碼；另存 H.264 播放副本，1280×720、4.8 秒、144 幀皆相同。來源及副本 hash 記錄於 `data/formal-200-v1/playback-media.json`，副本在 `media/q126/playback-h264.mp4`。API 另回傳 `playback_sources`，不覆寫 dataset、answer 或 output_messages；原檔保存於 `runtime/retrieval-playback/q126-original.mp4`。

原生 AttachmentTile 的失敗狀態改綁定媒體來源，換題／換網址可恢復播放器；支援顯示層相容副本及中英文失敗提示。7 個前端測試、11 個 API 測試、3 個瀏覽器測試及建置通過。公開站 q111、q126、q144、q174 實際播放通過，q126 seek 通過；q003、q104 顯示來源失效提示。200 題所有原始問答公開內容核對一致，資料集 hash 未變。報告、編碼核對與截圖：`runtime/retrieval-playback/`。這些檢查不是影片語意正確性驗證。

## 目前網站：可容納 240 題的分頁選題

選題區每頁最多 20 題，240 題分為 12 頁。支援翻頁、題號直接跳轉、回到目前題號與「下一個未完成」循環查找。題號保留，勾號標示已完成、圓點標示未儲存草稿；切題保留草稿，儲存並下一題跨頁時自動跟到該頁。中英文皆使用 i18n 翻譯。

6 個前端流程測試、TypeScript／Vite 建置及 2 個瀏覽器測試通過。以 240 題 fixture 驗證末題跳轉、跨頁保存、草稿保留、非法題號、部分末頁／全部完成與中英文 320px／390px 版面；240 題是 UI 測試資料，公開站仍使用原本 12 題 `preview-12-reels-en-v1`。已部署 web，公開站全部題目跳轉、語言切換、媒體及評分保存／重載通過，精確清除本次 1 筆測試評分。截圖與公開驗證報告：`runtime/navigation-240/`。

## 介面語言：i18n 中英文選單

介面採 i18next／react-i18next，由右上角選單切換繁中或 English，預設繁中並記住選擇；文案集中於 `web/src/locales/`。評分說明、選項、按鈕、保存／錯誤提示及附件／程式碼操作標籤皆依所選語言顯示。question 固定同時顯示英文與繁中。沿用 `preview-12-reels-en-v1` 的 12 題原始問答與評分。

4 個前端測試、TypeScript／Vite 建置與瀏覽器端到端測試通過，涵蓋切換時保留草稿、錯誤提示即時翻譯、question／原始回答保持內容，以及語言偏好重載。已更新評測 web 服務，公開網址不變。公開站 12 題、影片、評分保存／重載及中英文 390px 手機版驗證通過；精確清除本次驗證的 1 筆測試評分。報告與畫面：`runtime/i18n-selector/live-verification/`。先前並列版紀錄保留於 `runtime/bilingual-ui/live-verification/`。

## 目前資料集：reels 英文配音／字幕修復完成

資料集 `preview-12-reels-en-v1`（seed 20260917），12／12 題，模型仍為 gpt-5.6-luna。所有 query 保持原文，只重新取得 q009、q012 的原始回答與影片，其餘 10 題回答及 output_messages 逐字沿用 `preview-12-system-en-v1`，來源與各題指令政策均有記錄。舊資料、影片和評分保留。

根因：`../badminton-reels` 已有英文功能，但運行中 image 仍沒有 language 參數與英文 prompt。已驗證 repo 與新 image 的六項語言流程，重建並更新 reels，確認公開 MCP schema 有 `language: en | zh-TW`；重新建立 gateway 刷新工具定義。system instruction 明確設定 `language="en"`，優先於技能 UI 預設，user query 未加語言指令。沒有修改 AgentLoop、工具攔截、anchor 或工作重試行為，也沒有另寫 reels 的語言實作。

- 10 個 gateway 語言參數測試、21 個評測測試通過。
- 新影片 job 094、095 的 spec/result 均為 en；兩支共 20 段 text/subtitle_text 無中文字，固定開場／結尾為英文。
- 實際 TTS 紀錄兩次選用 English Guyzo 音色；ffprobe 確認含 AAC 音軌，成品擷取畫面確認英文字幕。環境不支援直接聽取音訊，未宣稱人工聽辨或 ASR 檢查。
- 12 題 user query、原始輸出與原 WebUI 歷史核對一致；回答文字均為英文。
- 網站 12 題、評分保存／重新載入、手機版及兩支新影片載入通過；已精確清除本次測試評分。五個圖表沿用原始內容及上一版互動驗證。
- q012 原始回答指出影片旁白有勝方描述不一致；影片約 59.12 秒，雖工具要求 30 秒。全部原樣保留，語言驗證不代表內容正確性。

完整預覽：`data/preview-12-reels-en-v1/preview.md`。部署、完整英文腳本、音色紀錄、成品字幕畫面及媒體報告：`runtime/reels-language-fix/`；原始輸出核對與網站報告：`runtime/preview-12-reels-en-v1/`。本次兩個 image 均已重建，新語言規則不依賴容器內暫時修改。

## 前一版：英文 system instruction 的 12 題回答

資料集 `preview-12-system-en-v1`（seed `20260917`），12／12 題完成，模型 `gpt-5.6-luna`。使用者明確允許英文要求放在 system instruction，禁止放在 user instruction。已只替換 repo 的 `nanobot/workspace/SOUL.md` 與運行中 gateway 的 workspace／啟動來源 SOUL 語言規則；原生 ContextBuilder 確認載入 system prompt。運行中的舊 SOUL 原本預設繁體中文。其餘服務程式碼與工具未改。

- 重用 `preview-12-sources-v1` 的 12 題，英文及繁中 query 均逐字相同；user query 沒有加語言指令。
- 12 份回答文字及 5 個圖表原始文字均為英文，CJK 掃描為 0；原始 WebSocket 輸出與原 WebUI 歷史 12／12 一致。
- 21 個相關測試通過；manifest 記錄 `gateway-system-english-v1`，避免混用先前的回答政策。
- 網站 12 題、Q1 門檻、評分保存與重新載入、手機版及影片載入檢查通過；五個圖表載入、選單互動與實際顯示英文標籤檢查通過；精確清除本次測試評分。
- **影片並非全英文**：第 9 題的 `script_summary` 為中文，原回答「English UI-selected voice/subtitles」與工具結果不符；第 12 題的敘事要求明示英文，結果仍保留中文主播開場。兩題均保留原始回覆與影片。部署中的 reels schema 沒有 `language` 欄位，system instruction 無法保證外部服務的固定內容變成英文。
- 第 5、6 題由模型選擇資料庫分析；第 11 題仍把後場站位頻率解釋為擊球次數。上述內容照實保留，未因品質重跑。

完整預覽：`data/preview-12-system-en-v1/preview.md`；部署備份、語言／媒體檢查、原始輸出核對與瀏覽器報告：`runtime/preview-12-system-en-v1/`。這些檢查不代表回答統計或新聞內容已驗證。舊資料與評分保留。

當時部署：只同步運行中容器的 workspace 與啟動來源，無需重啟。原 image 未重建；日後重新建立 gateway 容器，應由更新後的 repo 重建 image，保留新語言規則。

## 先前 locale-only 試跑：停止並保留

使用者要求所有回答為英文。已查明評測端先前沒有送出原生 WebUI 的 locale 欄位；英文 query 本身不能固定回答語言。現改用 `locale: en`，不增加 query 語言要求或 system prompt、不改 BadmintonGPT 核心／工具，也不翻譯既有回答。執行中 gateway 確認支援回覆語言提示；其 MCP 版本尚無工作區新版的工具 language 自動填入邏輯，因此沒有宣稱影片旁白語言一定受同樣控制。

新資料集 `preview-12-sources-en-v1`，原封不動重用 `preview-12-sources-v1` 的 12 題雙語 query，另行取得原始回答。manifest 記錄 `answer_locale: en` 與來源題庫；未複製舊答案。21 個相關測試通過，涵蓋 query 內容不變、原始輸出保留與 locale 政策隔離。網站保留上一版。實測 locale=en 的第 1、4 題仍有中文敘述，第 3 題仍有中文球種標籤；不能宣稱全英文。已停止此批後續提交，完成 4 題，第 5 題已送出並以原生唯讀 attach 完成後續輸出與歷史保存；未續跑或再次送出 query。使用者後續選擇修改 system instruction（見上方）。報告：`runtime/preview-12-sources-en-v1/language-audit.json`。

## 前一版：12 類主能力完整問答

資料集 `preview-12-sources-v1`，seed `20260917`，12／12 題完成，模型為 `gpt-5.6-luna`。五題送出前修訂，原始問題草稿與原因留存；回答階段只送英文 query，所有回答原樣保存。

- 12 類主能力各一題，全部取得原始回答；query 與回覆的 WebSocket 保存內容、原 WebUI 歷史核對均通過。
- 第 1 題實際只使用資料庫 query、檔案讀取與程式計算，未使用 badminton-analyze、reels 或影片搜尋。第 10 題實際使用 web_search 與 web_fetch。
- 第 1、2、4、6、7 題產生圖表，共 5 個；圖表載入及現有互動控制均通過瀏覽器檢查。
- 第 9、12 題影片分別約 60.29 秒與 30.93 秒，均可載入。第 12 題先搜尋，再由 BadmintonGPT 自行呼叫 reels 製作片段。
- 第 1、2、3、11、12 題曾在送出前修訂草稿，原稿、原因及修訂 prompt 全數保留。第 3 題改成可辨識的單場統計核實，偏離原抽樣 tactical_clips 範圍；修訂發生於回答前。
- 第 11 題雖詢問後場站位頻率，原始回答仍用「後場擊球頻率」解釋，且表列與排除場次的文字有不一致之處；未修改或重跑回答，供人工評測。
- 網站雙語問題、Q1 顯示門檻、評分保存與重新載入、手機頁面檢查通過；測試評分已依精確代碼清除。這些檢查不代表回答統計、新聞或影片內容的正確性已獲驗證。

完整問答：`data/preview-12-sources-v1/preview.md`。核對、能力使用觀察、網站與圖表互動報告及截圖皆在 `runtime/preview-12-sources-v1/`。

## 最新草稿：24 題 query（僅問題）

依要求生成 `preview-24-sources-v1`，seed `20260916`，24 題全部為 `question_ready`。12 類主能力各兩次；第 5、15 題為資料庫獨立分析，第 3、17 題為網路搜尋。兩個生成階段均收到對應 source；抽樣與 seed 核對一致。未送任何 BadmintonGPT query，無 gateway request 或回答，網站仍保留 `preview-5-presentation-v1`。

草稿觀察：第 12、24 題未完整指明比賽，第 17 題未指定排名項目，第 10、16 題模板相近，部分範圍仍偏向單場。保留實際生成內容供使用者審閱。預覽：`data/preview-24-sources-v1/preview.md`；紀錄：`runtime/preview-24-sources-v1/question-review.json`。

## 最新修正：資料庫獨立分析與網路搜尋

主能力池從 10 擴成 12 類：新增 `mcp_badminton-db_query` 與原生 `web_search`。每輪 12 題各一次，主能力比例各約 8.33%。MCP 定義與原生 web_search 定義分開保存，沒有新增假的 MCP function 或修改 BadmintonGPT 工具。

資料庫主題只抽資料庫能力，提供實際 schema，可問原始球種使用比例、回合長度、比分、得失分原因等；不要求 CoachAI ID、影片或外部分析指標。網路主題只抽 web_search，不讀本地資料庫，依新聞／排名／賽程／規則與 UTC 日期出題。原 Poisson(1)+1 抽樣值仍保存，這兩類因相容能力只有 1 個而截至 1；其他主題最多從 11 個相容能力抽樣，web 可作輔助，資料庫獨立類不作輔助。這是出題設計，BadmintonGPT 的實際工具使用仍由原服務決定。

政策：`database-web-capabilities-v3`、`database-web-context-v3`、`single-purpose-sources-v2`。預設新資料集 `preview-12-sources-v1`。21 個相關測試通過，涵蓋 12 類覆蓋、獨立來源不混工具、相容數量上限、無分析 ID／影片仍可取資料庫背景、網路類完全不存取 DB、四種網路主題與原始輸出保存。既有容器的原生 web_search 定義載入及 12 類池組合檢查通過，未執行搜尋。

另以實際資料庫離線驗證一輪 12 題的選取與背景組裝，報告 `runtime/database-web-check.json`。本次沒有生成新 query 或送出任何 BadmintonGPT 回答請求，網站與既有草稿保留。

## 最新草稿：精簡提示十題（僅問題）

依要求生成 `preview-10-concise-v1`，seed `20260916`，10 題皆為 `question_ready`，涵蓋全部 10 個主功能；未呼叫 BadmintonGPT 回答，無 gateway request 或回答。第 6 題誤將後場站位次數寫成擊球次數且未指明比賽，第 8 題縮成單場，第 9 題偏離戰術例子範圍且未指明比賽；保留實際結果供檢視，未自行修改或重生。預覽：`data/preview-10-concise-v1/preview.md`；檢查：`runtime/preview-10-concise-v1/question-review.json`。網站仍為 `preview-5-presentation-v1`。

## 前一批草稿：精簡提示五題（僅問題）

依要求生成 `preview-5-concise-v1`，seed `20260916`，5 題皆為 `question_ready`；未呼叫 BadmintonGPT 回答，無 gateway request 或回答。問題大致各一句；第 2 題仍縮成單場精華，未完全符合跨比賽球種範圍，保留供使用者檢視。預覽：`data/preview-5-concise-v1/preview.md`；檢查：`runtime/preview-5-concise-v1/question-review.json`。網站仍顯示前批 `preview-5-presentation-v1`。

## 最新修正：精簡提示與單一目的

新增 `prompt_policy: single-purpose-concise-v1`，新資料集預設 `preview-10-concise-v1`。intention 主要指令由 297 個英文詞縮至 74 個（字元減少 74.8%），query 由 326 個縮至 107 個（字元減少 67.7%）。呈現方式說明由 879 字元縮至 343 字元；範圍描述同步精簡，query 不再接收歷史意圖。完整技能、工具定義與資料背景保留，上述縮減數字只計指令文字。

每題一個核心目的，其他抽中工具只能支援同一目的，不增加任務／指標；呈現方式融入目的，互動圖表不指定控制元件。query 階段只改寫與翻譯，不新增要求，也不把資料使用規則寫進問題。單一目的屬於模型提示要求，沒有新增以關鍵字猜測需求數量的檢查。

20 個生成及原始輸出保存相關測試通過，包含新舊 prompt 政策隔離。長度比較報告：`runtime/concise-prompt-check.json`。本次尚未呼叫模型重新生成題目；網站與原始回答保留目前的 `preview-5-presentation-v1`，BadmintonGPT 回答流程未改動。

## 前一批：呈現需求 5 題預覽（保留）

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
