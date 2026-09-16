# BadmintonGPT 人工評測

先產生 **10 題**英文／繁中問題。回答階段只將英文問題送至既有 BadmintonGPT WebSocket 介面，保存其原始輸出。意圖、問題生成使用 `gpt-5.6-luna`；送出問題前確認 gateway 的即時模型也為 `gpt-5.6-luna`，不修改 gateway 設定。確認預覽後，另開 300 題資料集。

目前網站顯示 **5 題**呈現需求預覽：`preview-5-presentation-v1`（seed `20260916`），5／5 題完成。呈現依序為文字、影片、影片、互動視覺化、比較圖表；第 4、5 題都產生互動圖表並通過篩選器操作檢查。第 3 題第二支影片載入遭瀏覽器阻擋，第 4 題另附與馬琳影片相關的內容，均保留原始輸出供評測。完整意圖、問題、回答與限制：`data/preview-5-presentation-v1/preview.md`。舊題庫與評分保留。

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

# 生成 10 題。這會使用 OpenAI API 及既有 MCP，並可能建立遠端影片工作。
docker compose -f human-evaluation/compose.yaml run --rm generator --count 10 --dataset preview-10-presentation-v1 --resume

# 查看臨時公開網址。
docker compose -f human-evaluation/compose.yaml logs tunnel
```

本機網址：<http://127.0.0.1:8810>。公開網址由 Cloudflare Quick Tunnel 動態提供；Tunnel 重啟後可能改變。依指定不設密碼或 Cloudflare Access。評測代碼只是結果識別碼，不是驗證身份的密碼。

題庫尚未生成時，網站顯示準備中。生成每完成一題會原子更新題庫；重新整理即可載入，不需重啟網站。

## 評測行為

- 輸入 3–64 字元的評測代碼（英文字母、數字、底線、連字號，區分大小寫）。同代碼可跨瀏覽器恢復進度；相同代碼的同一題以最後一次儲存為準。
- 每題並列英文與繁中問題。先回答 Q1；只有「合理／有些牽強」才顯示原始回答與 Q2。
- Q1 改成「不合理」會清除 Q2；此時只需 Q1 即可完成。其他選項必須填 Q2 才算完成。
- 「儲存」可保存部分評分；「儲存並下一題」要求完整評分。進度只計算伺服器已確認儲存的完整評分。
- 題號切換會保留當頁尚未保存的草稿；離開或重新整理前會提示未儲存。未保存時停用切換評測代碼。
- 重用 `vendor/nanobot/webui` 的 Markdown、公式、程式碼、視覺化與附件元件；沒有另寫一套回答格式轉換器。原元件的公式語法為 `$$…$$` 或其支援的跳脫括號，單一 `$` 保持原行為。

## 生成與續跑

1. 保存 `skills/**/SKILL.md` 快照；連線取得實際啟用的 MCP 工具池，工具不齊全時停止。
2. 意圖抽樣池只包含 10 個直接對應使用者需求的工具：8 個分析功能、`start_video_retrieval`、`generate_reel`。數量使用 `K = Poisson(λ=1) + 1`，平均約 2 個，約 73.6% 的題目只抽 1–2 個；僅以可用工具數 10 為上限，不再限制最多 5 個。主功能以固定 seed 洗牌，每輪 10 題各出現一次，其餘 `K - 1` 個功能隨機不重複抽取。提供名稱與完整定義給第一次模型呼叫，以主功能形成一個連貫需求，其他功能只作可選輔助。資料庫、狀態／結果查詢、等待、健康檢查與 collection 探索不作為意圖抽樣來源；BadmintonGPT 仍可自行使用所有原有工具。
3. 不再抽樣資料類別。每題都提供代表比賽的 `match`、`rally`、`shots` 三類背景（擊球資料仍為抽中回合的前 12 筆），另提供 `focus` 選手／年份、`related_matches` 相關比賽清單、`available_shot_types` 球種及 `coverage` 資料範圍。年度／跨賽事／選手比較範圍只列目標年份；跨比賽需求至少有兩場來源，跨賽事至少兩個賽事。排除練習賽、缺選手名稱與無擊球資料紀錄；代表比賽仍須符合工具的分析 ID／影片條件。資料範圍是資料庫收錄內容，不代表完整年度或生涯。
4. 題目依序輪替六種 `query_scope`：選手年度表現、選手球種、戰術影片、跨賽事變化、選手比較、單場比賽。intention 及雙語 query 生成都收到範圍要求與實際目標選手，背景不要求逐項寫進問題。問題需完整具體，不能要求尚未提供的 match ID 或引用未附上的序列。檢查英文目標選手、雙語年份、常見缺漏資訊引用、跨賽事措辭及繁中混入非預期語系字元；未通過只重生問題草稿（每次執行最多 3 次），保存每次 prompt、回應與錯誤。這些檢查不能取代人工語意評估，不會因回答品質而重跑 BadmintonGPT。
5. 獨立選擇 `presentation`：分析題從文字、比較圖表、互動視覺化等機率抽選；失分分布及後場站位另可抽到球場圖（四者等機率）。影片搜尋／製作主功能固定為影片需求。使用獨立 seed，不改變 function 數量或範圍；短批次不保證涵蓋全部形式。intention 與雙語 query 都明確要求所選呈現方式，圖表比較及互動控制須配合題目範圍。球場圖不得虛構座標或軌跡。`skills/visualise/SKILL.md` 仍是技能背景，不加入 MCP function 抽樣池。
6. 用既有 WebUI 的 `/webui/bootstrap` 取得連線資訊，開啟新對話，只送出一個 `message`，其 `content` 與 `query_en` 完全相同。
7. 等待原生 `turn_end`，逐筆保存原始 WebSocket frame。僅依原生串流協定組合顯示訊息，保留原文字、空白及附件網址。

生成會將技能文字、抽樣羽球資料、問題及回答所需工具結果送至 OpenAI API，並呼叫設定的 MCP。憑證只作對應服務的驗證，不寫入提示、前端或已解析的設定檔。模型名稱固定為 `gpt-5.6-luna`。

```bash
# 中斷或暫時失敗後接續相同資料集；已完成題目不重新生成。
docker compose -f human-evaluation/compose.yaml run --rm generator --count 10 --dataset preview-10-presentation-v1 --resume

# 僅生成雙語問題，稍後用上一行接續回答。
docker compose -f human-evaluation/compose.yaml run --rm generator --count 10 --dataset preview-10-presentation-v1 --questions-only --resume

# 預覽確認後才執行：使用新資料集，不覆盖預覽問答與評分。
docker compose -f human-evaluation/compose.yaml run --rm generator --count 300 --dataset full-300 --resume
```

預設 seed 為 `20260915`，每題回答上限 1800 秒。續跑需使用原 count、seed 和模型；新一輪使用新的 `--dataset`。同資料集有檔案鎖，禁止兩個生成程序同時寫入。

意圖抽樣規則版本記錄於 manifest 的 `intention_sampling`，目前為 `user-capabilities-poisson-v2`；不同版本不能混合續跑。manifest 另記錄數量分布及主功能輪替規則，每題記錄 `sampled_tool_count`（套用工具池上限前）、`primary_tool` 與 `selected_tools`。數量、主功能及其餘功能使用獨立且可重現的亂數來源，單題重試或 `--only` 不會改變預定抽樣。

資料政策記錄為 `data_sampling: full-context-scopes-v2`，manifest 保存六種範圍順序；每題保存 `query_scope`、完整 `sampled_data` 與同內容的 `query_data`。function 數量維持 `Poisson(1) + 1`，不受提問範圍影響。最近 30 題的意圖與範圍作為避免重複的參考，不把先前完整題目當範例。

呈現政策記錄為 `presentation_sampling: compatible-presentation-v1`；manifest 保存呈現選項及規則，每題保存 `presentation`。舊資料集不能混用此政策續跑。這是出題要求，不保證 BadmintonGPT 一定產生圖表；回答照原樣保留。已依新規則完成 `preview-5-presentation-v1` 五題並更新網站。

上例使用 `preview-10-presentation-v1`。試跑 5 題使用 `--count 5 --seed 20260916 --dataset preview-5-presentation-v1 --resume`；可先加 `--questions-only` 檢查完整問題，再用同一參數接續回答。舊資料集與評分保留，不能混用新規則續跑。

### 回答階段的界線

評測端不建立或修改 AgentLoop，不攔截工具、不快取工具結果、不控制工作重試、不操作 reels 工作狀態、不補提示或改寫回答。anchor 是否可用及如何降級由 BadmintonGPT 自己處理；問題生成也不再自動加入禁用 anchor 的條件。

題目不強制加入英文作答要求；傳送端不另加 system prompt、locale 或訊息。BadmintonGPT 若以中文回答，原樣保留，不翻譯或因此重跑。現有 `preview-5-intents-v1` 的第 2、3 題就是英文 query 得到中文原始回答。

`blackbox_client.py` 不匯入任何 agent 或 MCP 執行元件。gateway 自己依原本流程保存對話與記憶，評測端不修改這些行為。MCP 連線只在問題生成前讀取工具定義，與回答階段分開。送出的 `request.json` 和收到的 `output-frames.jsonl` 可逐筆稽核。

`--only 3` 可只處理第 3 題，已完成題目仍會跳過。已送出但連線中斷的 query 不會自動重新提交或傳送取消命令；保存 session ID 和原始輸出供檢查。`receive_existing.py --item q006` 可透過原生 `attach` 訂閱仍在執行中的既有對話，只收取輸出，另存於該題 `gateway/reconnected/`，不送新 query 或改動題庫。BadmintonGPT 回答中的服務錯誤與能力限制照實保存，不因答案品質重跑。

舊 `data/preview-10/` 使用過工具攔截，不作為有效評測資料，已從網站撤下。後續 `preview-10-blackbox` 及 `preview-5-intents-v1`、`v2`、`v3` 、`preview-5-scopes-v2` 與目前的 `preview-5-presentation-v1` 都只透過原介面取得回答；各批問答與評分分開留存。

### 唯讀核對

```bash
docker compose -f human-evaluation/compose.yaml run --rm --entrypoint python generator /evaluation/verify_outputs.py --dataset preview-5-presentation-v1
```

核對以實際收到的 WebSocket frame 為準，並另外比對原 WebUI 歷史 API。目前 5 題全部通過，歷史 API 也一致。前一批 10 題均通過原始輸入／輸出核對；其中第 10 題的原歷史 API 只保留結尾摘要，評測仍完整保存 WebSocket 傳回的兩段輸出。各批報告保存在 `runtime/<dataset>/output-verification.json`。

## 資料與匯出

| 路徑 | 用途 |
|---|---|
| `data/<dataset>/manifest.json` | 生成設定與技能快照 |
| `data/<dataset>/tool-pool.json` | 實際 MCP 工具定義 |
| `data/<dataset>/intention-tool-pool.json` | 僅用於意圖抽樣的功能定義，不影響 BadmintonGPT 可用工具 |
| `data/<dataset>/items/` | 每題狀態、雙語問題、抽樣來源、提問範圍、呈現方式、實際出題背景與原始回答 |
| `data/<dataset>/generation/` | 問題生成提示／回應，以及 gateway 原始請求／輸出 |
| `data/<dataset>/dataset.json` | 已完成題目的集合 |
| `data/<dataset>/generation/<item>/gateway/` | `request.json`、`output-frames.jsonl`、`output.json` |
| `data/ratings.sqlite3` | 依資料集、評測代碼、題號保存的評分 |
| `runtime/` | 工具探索設定、瀏覽器測試資料及舊診斷備份 |

上述執行產物由本目錄 `.gitignore` 排除；仍保存在本機，不會隨容器重建消失。備份時保留整個 `data/`，並先停止寫入評分以便一致備份 SQLite。

```bash
python3 human-evaluation/export.py --dataset preview-5-presentation-v1 --format csv > human-evaluation/data/ratings.csv
python3 human-evaluation/export.py --dataset preview-5-presentation-v1 --format json > human-evaluation/data/ratings.json
```

前端 API 只傳題目、回答與附件，不傳生成意圖、原始事件紀錄、憑證或評分資料庫。評分匯出只提供本機指令。

API：`GET /api/dataset`、`GET /api/evaluators/{code}/ratings`、`PUT /api/datasets/{dataset}/evaluators/{code}/ratings/{item}`、`GET /api/media/{item}/{filename}`。儲存 body 為 `{q1, q2}`，使用英文 enum，未回答值為 `null`。Q2 與 Q1 不相容時回傳 422；未知題目回傳 404；資料集版本不符回傳 409。

要切換網站題庫，修改本目錄 Compose 的 `EVAL_DATASET` 為 `/evaluation/data/full-300/dataset.json`，再重建 web 容器。不同資料集評分分開保存。

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
