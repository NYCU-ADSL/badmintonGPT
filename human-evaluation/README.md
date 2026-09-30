# BadmintonGPT 人工評測

先產生 **12 題**英文／繁中問題。回答階段只將英文問題送至既有 BadmintonGPT WebSocket 介面，保存其原始輸出。意圖、問題生成使用 `gpt-5.6-luna`；送出問題前確認 gateway 的即時模型也為 `gpt-5.6-luna`，不修改 gateway 模型設定。正式批次為 200 題，獨立保存於 `formal-200-v1`。

目前網站已部署 **200 題**正式問答 `formal-200-v1`，每頁 20 題，共 10 頁。200 題原始輸出核對通過；播放器相容副本及失效來源紀錄見 `STATUS.md`。

先前預覽顯示 **12 題**完整問答：`preview-12-reels-en-v1`（seed `20260917`）。所有 user query 保持原文，只重新取得第 9、12 題的原始回答及影片，其餘 10 題回答逐字沿用 `preview-12-system-en-v1`。12 題原始輸出及 WebUI 歷史核對通過；網站、評分保存、手機版及兩支新影片載入通過。五個圖表內容與上一版完全相同，保留既有英文標籤與互動驗證紀錄。

**影片語言修復已部署**：舊 reels 容器沒有語言參數及英文模板。已從 `../badminton-reels` 重建並更新服務、刷新 gateway 的工具定義，system instruction 明確指定 `language="en"`。兩個新 job 的 spec/result 都是 `en`；共 20 段旁白及字幕沒有中文字，包含英文固定開場／結尾；TTS 兩次均選用英文音色 Guyzo，成品字幕畫面已確認。音訊輸入在本環境不受支援，沒有宣稱人工聽辨或 ASR 驗證；檢查依據為完整 TTS 文字、實際音色紀錄、音軌及字幕成品。

舊影片、資料集與評分均保留；本次沒有翻譯、剪改或覆寫任何原始回答。第 12 題的原始回答指出影片旁白有勝方描述不一致，該問題仍保留供人工評測，語言檢查不代表戰術內容正確。完整預覽：`data/preview-12-reels-en-v1/preview.md`；部署及影片語言證據：`runtime/reels-language-fix/`；原始輸出／網站核對：`runtime/preview-12-reels-en-v1/`。

## 啟動

以下指令從專案根目錄執行。需先有執行中的 BadmintonGPT gateway（網路內 `http://gateway:8765`）、既有的 `badmintongpt-gateway:0.2.1` 映像與 `badmintongpt_default` 網路、可用的 badminton-db 服務，以及專案根目錄 `.env` 中的 OpenAI／羽球 MCP 憑證。

```bash
# 讓評測容器以目前使用者身份寫入資料。
python3 - <<'PY'
import os
from pathlib import Path
Path('human-evaluation/.env').write_text(f'EVAL_UID={os.getuid()}\nEVAL_GID={os.getgid()}\n')
PY

npm --prefix human-evaluation/web ci
npm --prefix human-evaluation/web run build
mkdir -p human-evaluation/data
docker compose -f human-evaluation/compose.yaml up -d --build web tunnel

# 生成 12 題。這會使用 OpenAI API 及既有 MCP，並可能建立遠端影片工作。
docker compose -f human-evaluation/compose.yaml run --rm generator --count 12 --seed 20260917 --dataset preview-12-reels-en-v1 --resume

# 查看臨時公開網址。
docker compose -f human-evaluation/compose.yaml logs tunnel
```

本機網址：<http://127.0.0.1:8810>。公開網址由 Cloudflare Quick Tunnel 動態提供；Tunnel 重啟後可能改變。依指定不設密碼或 Cloudflare Access。評測代碼只是結果識別碼，不是驗證身份的密碼。

題庫尚未生成時，網站顯示準備中。生成每完成一題會原子更新題庫；重新整理即可載入，不需重啟網站。

## 評測行為

介面使用 i18next／react-i18next，由右上角選單切換繁體中文或 English，預設繁中，並在瀏覽器記住語言選擇。登入說明、評分標準、導航、保存狀態、錯誤提示與附件／程式碼操作標籤皆跟隨所選語言；切換不會清除評分草稿。每題 question 仍同時顯示英文與繁中，BadmintonGPT 回答依原始輸出顯示。評測翻譯檔位於 `web/src/locales/`，與原生 renderer 的 `common` namespace 分開。

- 輸入 3–64 字元的評測代碼（英文字母、數字、底線、連字號，區分大小寫）。同代碼可跨瀏覽器恢復進度；相同代碼的同一題以最後一次儲存為準。
- 選題區每頁最多 20 題（240 題分為 12 頁），支援上一／下一頁、題號直接跳轉、回到目前題號，以及「下一個未完成」（以已儲存進度判斷並循環尋找）。已完成題目保留題號與勾號，未儲存草稿以圓點標示；跨頁切題保留草稿，儲存並下一題會自動顯示所在頁。
- 每題並列英文與繁中問題。先回答 Q1；只有「合理／有些牽強」才顯示原始回答與 Q2。
- Q1 改成「不合理」會清除 Q2；此時只需 Q1 即可完成。其他選項必須填 Q2 才算完成。
- 「儲存」可保存部分評分；「儲存並下一題」要求完整評分。進度只計算伺服器已確認儲存的完整評分。
- 題號切換會保留當頁尚未保存的草稿；離開或重新整理前會提示未儲存。未保存時停用切換評測代碼。
- 重用 `vendor/nanobot/webui` 的 Markdown、公式、程式碼、視覺化與附件元件；沒有另寫一套回答格式轉換器。原元件的公式語法為 `$$…$$` 或其支援的跳脫括號，單一 `$` 保持原行為。

## 生成與續跑

1. 保存 `skills/**/SKILL.md` 快照及完整 MCP 定義；另載入現有原生 `web_search` 定義（不執行搜尋）。確認 12 類出題能力皆可用；web 設定停用時停止。
2. 主能力池共 12 類：原 8 個分析功能、影片搜尋、精華製作，加上 `badminton-db.query` 資料庫分析與原生 `web_search`。固定 seed 洗牌，每輪 12 題各當主功能一次，比例各 1/12。保留原始 `K = Poisson(1) + 1` 抽樣；資料庫／網路主題各只有 1 個相容能力，其餘主功能最多從 11 個能力選取（資料庫獨立類不當輔助，web 可作輔助）。其餘抽中能力僅支援同一目的。資料表結構、狀態／結果、等待、健康檢查與 collection 探索仍不作為主題。
3. 不再抽樣資料類別。每題都提供代表比賽的 `match`、`rally`、`shots` 三類背景（擊球資料仍為抽中回合的前 12 筆），另提供 `focus` 選手／年份、`related_matches` 相關比賽清單、`available_shot_types` 球種及 `coverage` 資料範圍。年度／跨賽事／選手比較範圍只列目標年份；跨比賽需求至少有兩場來源，跨賽事至少兩個賽事。排除練習賽、缺選手名稱與無擊球資料紀錄；代表比賽仍須符合工具的分析 ID／影片條件。資料範圍是資料庫收錄內容，不代表完整年度或生涯。 資料庫獨立類不要求分析 ID 或影片，另提供實際三表欄位給 intention 與 query，僅設計可由原始欄位統計的題目，不要求外部分析指標；抽到戰術影片範圍時改用球種分析。網路獨立類不讀資料庫，提供 UTC 參考日期及新聞、排名、賽程或規則主題，採 public_web 範圍；每四輪覆蓋四種主題。
4. 題目依序輪替六種 `query_scope`：選手年度表現、選手球種、戰術影片、跨賽事變化、選手比較、單場比賽。intention 及雙語 query 生成都收到範圍要求與實際目標選手。intention 只描述一個核心目的；query 只做簡短自然改寫與翻譯，不擴充需求。背景不要求逐項寫進問題，資料使用注意事項也不寫成使用者要求。問題需完整具體，不能要求尚未提供的 match ID 或引用未附上的序列。檢查英文目標選手、雙語年份、常見缺漏資訊引用、跨賽事措辭及繁中混入非預期語系字元；未通過只重生問題草稿（每次執行最多 3 次），保存每次 prompt、回應與錯誤。這些檢查不能取代人工語意評估，不會因回答品質而重跑 BadmintonGPT。
5. 獨立選擇 `presentation`：分析與資料庫題從文字、比較圖表、互動視覺化等機率抽選；失分分布及後場站位另可抽到球場圖（四者等機率）。影片搜尋／製作主功能固定為影片需求。使用獨立 seed，不改變 function 數量或範圍；短批次不保證涵蓋全部形式。呈現方式融入同一目的；文字題直接提問，圖表題只要求相應圖表，不指定篩選器或額外交付項目。球場圖不得虛構座標或軌跡。`skills/visualise/SKILL.md` 仍是技能背景，不加入 MCP function 抽樣池。 網路獨立類固定直接文字提問。
6. 用既有 WebUI 的 `/webui/bootstrap` 取得連線資訊，開啟新對話，只送出一個 `message`，其 `content` 與 `query_en` 完全相同；使用原介面的 `locale: en` 指定英文回覆，相當於原 WebUI 語言選擇器。
7. 等待原生 `turn_end`，逐筆保存原始 WebSocket frame。僅依原生串流協定組合顯示訊息，保留原文字、空白及附件網址。

生成會將技能文字、抽樣羽球資料、問題及回答所需工具結果送至 OpenAI API，並呼叫設定的 MCP。憑證只作對應服務的驗證，不寫入提示、前端或已解析的設定檔。模型名稱固定為 `gpt-5.6-luna`。

```bash
# 中斷或暫時失敗後接續相同資料集；已完成題目不重新生成。
docker compose -f human-evaluation/compose.yaml run --rm generator --count 12 --seed 20260917 --dataset preview-12-reels-en-v1 --resume

# 僅生成雙語問題，稍後用上一行接續回答。
docker compose -f human-evaluation/compose.yaml run --rm generator --count 12 --seed 20260917 --dataset preview-12-reels-en-v1 --questions-only --resume

# 預覽確認後才執行：使用新資料集，不覆盖預覽問答與評分。
docker compose -f human-evaluation/compose.yaml run --rm generator --count 200 --seed 2026091701 --dataset formal-200-v1 --resume
```

預設 seed 為 `20260915`，每題回答上限 1800 秒。續跑需使用原 count、seed 和模型；新一輪使用新的 `--dataset`。同資料集有檔案鎖，禁止兩個生成程序同時寫入。

意圖政策為 `intention_sampling: database-web-capabilities-v3`。每題保存 `question_source`（capabilities／database／web）、主能力、選取能力、原始 Poisson 數量及 `eligible_tool_count`。資料庫／網路獨立類將數量截至 1，其他類按相容能力池截斷。這些規則只控制出題，不攔截或限制 BadmintonGPT 的實際工具使用。

資料政策為 `data_sampling: database-web-context-v3`。本地分析題保留完整 match/rally/shots 與相關目錄，資料庫類另附 schema；網路類保存 topic、as_of 與空的選手／年份 focus，沒有本地比賽背景。最近 30 題的意圖與範圍只傳入 intention 階段作為避免重複的參考。

呈現政策記錄為 `presentation_sampling: compatible-presentation-v1`；manifest 保存呈現選項及規則，每題保存 `presentation`。舊資料集不能混用此政策續跑。這是出題要求，不保證 BadmintonGPT 一定產生圖表；回答照原樣保留。先前完成 `preview-5-presentation-v1`，目前網站已更新為 `preview-12-reels-en-v1`。

提示政策為 `prompt_policy: single-purpose-sources-v2`，保留簡短的單一目的指令，另傳 source 描述。資料庫類的題目以可由資料表回答為目標，網路類以公開來源為目標；不把工具禁令或 SQL 步驟寫進問題。這是出題約束，仍需檢視模型生成結果。新舊政策不得混合續跑；已依此版本完成 `preview-12-sources-v1`，目前以相同 query 的 `preview-12-reels-en-v1` 顯示回答。

上例使用 `preview-12-reels-en-v1`，一輪可覆蓋 12 類主功能。可先加 `--questions-only` 檢視問題，再另行執行回答。舊題庫與評分保留，不能混用新規則續跑。

### 回答階段的界線

評測端不建立或修改 AgentLoop，不攔截工具、不快取工具結果、不控制工作重試、不操作 reels 工作狀態、不補提示或改寫回答。anchor 是否可用及如何降級由 BadmintonGPT 自己處理；問題生成也不再自動加入禁用 anchor 的條件。

使用者已允許把全英文要求加在 **BadmintonGPT 原生 system instruction**，禁止加在 user instruction。已在 repo 的 `nanobot/workspace/SOUL.md`，以及執行中 gateway 的 workspace／啟動來源 SOUL 中，只替換語言規則：回答、表格及圖表文字使用英文，生成影片要求英文旁白與字幕；查詢值、識別碼與 URL 保持原值。原生 ContextBuilder 已確認將規則載入 system prompt，不必重啟。這是服務層規則，適用該 gateway 的後續對話。

user query 完全不變，仍傳送原生 `locale: en`。manifest 以 `answer_instruction_policy: gateway-system-english-v2` 隔離舊資料集，system 明確傳入 `language="en"` 並優先於技能中的 UI 預設。`preview-12-system-en-v1` 曾重用相同 12 題取得新回答，本次 `preview-12-reels-en-v1` 只更新兩道影片題；舊混合語言資料及先前 locale-only 試跑 `preview-12-sources-en-v1` 保留。若模型仍違反語言要求，照實記錄，不翻譯或自動重跑。部署備份與驗證位於 `runtime/preview-12-system-en-v1/`。

2026-09-17 已一併檢查 `../badminton-reels` 並重建兩個服務：舊 reels image 沒有語言參數及英文模板，即使 repo 已更新仍會輸出中文。新版遠端 MCP schema 已確認包含 `language`，gateway 也刷新了工具定義與 system instruction。既有影片不會隨部署自動改變；`preview-12-reels-en-v1` 只重新取得兩道影片題，其餘 10 題原始輸出逐字沿用並記錄來源。

`blackbox_client.py` 不匯入任何 agent 或 MCP 執行元件。gateway 自己依原本流程保存對話與記憶，評測端不修改這些行為。MCP 連線只在問題生成前讀取工具定義，與回答階段分開。送出的 `request.json` 和收到的 `output-frames.jsonl` 可逐筆稽核。

`--only 3` 可只處理第 3 題，已完成題目仍會跳過。已送出但連線中斷的 query 不會自動重新提交或傳送取消命令；保存 session ID 和原始輸出供檢查。`receive_existing.py --item q006` 可透過原生 `attach` 訂閱仍在執行中的既有對話，只收取輸出，另存於該題 `gateway/reconnected/`，不送新 query 或改動題庫。BadmintonGPT 回答中的服務錯誤與能力限制照實保存，不因答案品質重跑。

舊 `data/preview-10/` 使用過工具攔截，不作為有效評測資料，已從網站撤下。後續 `preview-10-blackbox` 及 `preview-5-intents-v1`、`v2`、`v3` 、`preview-5-scopes-v2` 、`preview-5-presentation-v1` 、`preview-12-sources-v1` 、`preview-12-system-en-v1` 與目前的 `preview-12-reels-en-v1` 都只透過原介面取得回答；各批問答與評分分開留存。

### 唯讀核對

```bash
docker compose -f human-evaluation/compose.yaml run --rm --entrypoint python generator /evaluation/verify_outputs.py --dataset preview-12-reels-en-v1
```

核對以實際收到的 WebSocket frame 為準，並另外比對原 WebUI 歷史 API。先前 12 題全部通過，歷史 API 也一致。前一批 10 題均通過原始輸入／輸出核對；其中第 10 題的原歷史 API 只保留結尾摘要，評測仍完整保存 WebSocket 傳回的兩段輸出。各批報告保存在 `runtime/<dataset>/output-verification.json`。

### 影片播放相容性

保留 BadmintonGPT 原文與原始 URL。需要時，`data/<dataset>/playback-media.json` 為特定原始影片指定 `media/<item>/` 中的瀏覽器相容編碼副本；API 以獨立的 `playback_sources` 傳給原生附件元件，僅改變播放器來源。q126 的 mp4v 已提供同解析度、長度及幀數的 H.264 副本。來源回傳 404 的 q003／q104 不替換成其他影片，顯示失敗提示供評測。備份時需包含此 manifest、`media/` 與 `runtime/retrieval-playback/` 的原檔／驗證紀錄。

## 資料與匯出

| 路徑 | 用途 |
|---|---|
| `data/<dataset>/manifest.json` | 生成設定與技能快照 |
| `data/<dataset>/tool-pool.json` | 實際 MCP 工具定義 |
| `data/<dataset>/builtin-tool-pool.json` | 原生 web_search 定義，與完整 MCP 快照分開保存 |
| `data/<dataset>/intention-tool-pool.json` | 僅用於意圖抽樣的功能定義，不影響 BadmintonGPT 可用工具 |
| `data/<dataset>/items/` | 每題狀態、雙語問題、抽樣來源、提問範圍、呈現方式、實際出題背景與原始回答 |
| `data/<dataset>/generation/` | 問題生成提示／回應，以及 gateway 原始請求／輸出 |
| `data/<dataset>/dataset.json` | 已完成題目的集合 |
| `data/<dataset>/generation/<item>/gateway/` | `request.json`、`output-frames.jsonl`、`output.json` |
| `data/ratings.sqlite3` | 依資料集、評測代碼、題號保存的評分 |
| `runtime/` | 工具探索設定、瀏覽器測試資料及舊診斷備份 |

上述執行產物由本目錄 `.gitignore` 排除；仍保存在本機，不會隨容器重建消失。備份時保留整個 `data/`，並先停止寫入評分以便一致備份 SQLite。

```bash
python3 human-evaluation/export.py --dataset preview-12-sources-v1 --format csv > human-evaluation/data/ratings.csv
python3 human-evaluation/export.py --dataset preview-12-sources-v1 --format json > human-evaluation/data/ratings.json
```

前端 API 只傳題目、回答與附件，不傳生成意圖、原始事件紀錄、憑證或評分資料庫。評分匯出只提供本機指令。

API：`GET /api/dataset`、`GET /api/evaluators/{code}/ratings`、`PUT /api/datasets/{dataset}/evaluators/{code}/ratings/{item}`、`GET /api/media/{item}/{filename}`。儲存 body 為 `{q1, q2}`，使用英文 enum，未回答值為 `null`。Q2 與 Q1 不相容時回傳 422；未知題目回傳 404；資料集版本不符回傳 409。

要切換網站題庫，修改本目錄 Compose 的 `EVAL_DATASET` 為 `/evaluation/data/formal-200-v1/dataset.json`，再重建 web 容器。不同資料集評分分開保存。

## 驗證與維護

```bash
uv venv human-evaluation/.venv
uv pip install --python human-evaluation/.venv/bin/python -r human-evaluation/requirements.txt
human-evaluation/.venv/bin/python -m pytest human-evaluation/tests -q
npm --prefix human-evaluation/web test

# 瀏覽器測試需 ffmpeg 與 Playwright Chromium；使用完全獨立的測試題庫。
cd human-evaluation/web
npx playwright install chromium
npm run test:e2e
```

若要使用現有 Chromium，可設定 `EVAL_BROWSER_EXECUTABLE=/absolute/path/to/chrome-headless-shell`。瀏覽器測試驗證真實元件的表格、公式、互動圖表、影片載入、保存恢復、Q2 清除與手機寬度；截圖在 `test-results/`。測試題庫不會發布至公開網站。

```bash
docker compose -f human-evaluation/compose.yaml ps
docker compose -f human-evaluation/compose.yaml logs --tail 80 web tunnel
docker compose -f human-evaluation/compose.yaml down
```

網站服務與原 BadmintonGPT 使用不同 Compose 專案。停止本評測服務不會停止既有 gateway／資料庫。
