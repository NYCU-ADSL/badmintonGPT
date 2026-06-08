# mcp-test — MCP server 一致性測試工具

子計畫做完 MCP server 後，用這支 CLI 快速驗收：把它指向你的 MCP 端點，跑一系列**唯讀**檢查
（**不會呼叫任何業務工具 → 對你的 server 零副作用**），輸出報告 + exit code，可放 CI。

檢查涵蓋：**通用 MCP 協定** + **本團隊指南慣例**（見 `REMOTE_MCP_SERVER_GUIDE.md`）。

---

## 安裝 / 執行

本 repo 內（已備好 `.venv`）：
```bash
.venv/bin/python -m mcp_test <MCP_URL> [options]
```

其他子計畫要用：把 `mcp_test/` 這個資料夾複製過去即可（只依賴 `mcp`、`jsonschema`、`httpx`）：
```bash
pip install mcp jsonschema httpx        # 或 uv add
python -m mcp_test <MCP_URL> [options]
```

## 用法

```bash
# 1) 遠端 MCP（Streamable HTTP）+ Cloudflare Access service token
python -m mcp_test https://my-mcp.<zone>/mcp \
  --header "CF-Access-Client-Id: $MYMCP_CF_CLIENT_ID" \
  --header "CF-Access-Client-Secret: $MYMCP_CF_CLIENT_SECRET"

# 2) 容器化的內網 MCP（Streamable HTTP，compose 內網，無 auth）
#    本 repo 的 badminton-db 就是這種：自己的容器、服務名 badminton-db、:8801/mcp。
#    從 sibling 容器（同 compose 網路，例如 gateway 裡）：
python -m mcp_test http://badminton-db:8801/mcp
#    從 host（HOST/DEV 模式，server 跑成本地 HTTP：
#    MCP_HOST=127.0.0.1 python mcps/badminton-db/server.py）：
python -m mcp_test http://127.0.0.1:8801/mcp

# 3) 本地 stdio server（如 mcps/util/server.py，或用 MCP_TRANSPORT=stdio 跑 badminton-db）
python -m mcp_test --stdio "/path/.venv/bin/python /path/mcps/util/server.py" --env SOME_VAR=/abs/path

# 4) CI 用 JSON 輸出；--strict 把 WARN 也當失敗
python -m mcp_test https://my-mcp.<zone>/mcp --header "..." --json --strict
```

選項：
| 選項 | 說明 |
|---|---|
| `<URL>` | 遠端 MCP 端點（如 `https://host/mcp`）；與 `--stdio` 二擇一 |
| `--stdio "CMD ARGS"` | 改測本地 stdio server |
| `--env K=V` | 給 `--stdio` 的環境變數（可重複） |
| `--header "K: V"` | HTTP 標頭/認證（可重複） |
| `--base-url URL` | healthz / auth-gating 用；預設＝去掉結尾 `/mcp` |
| `--timeout 30` | 每步逾時秒數 |
| `--json` | 輸出 JSON（含 summary、ok）|
| `--strict` | WARN 視為失敗 |

**Exit code**：有 FAIL → 非 0；否則 0（`--strict` 時 WARN 也算失敗）。

---

## 檢查項目

**A. 通用 MCP 協定**
- connect + `initialize` 握手；記錄 serverInfo / protocolVersion。
- `tools/list` ≥ 1 個工具；工具名唯一、格式合法、**每個都有 description**、`inputSchema` 是合法 JSON Schema。
- `resources/list`、`prompts/list`（server 有宣告才測；空的算過）。
- 呼叫**不存在的工具** → 應回正規 MCP 錯誤（協定層，不跑任何業務邏輯）。

**B. 本團隊指南慣例**（預設 WARN，`--strict` 才 FAIL）
- `/healthz` 帶 token 回 2xx。
- **未帶 token 被擋**（Cloudflare Access → 401/403）。
- **非同步 job 慣例**：偵測 `start_*`/`generate_*` + `*status*` + `*result*`（INFO）。
- `/files` 下載 & 錯誤格式：唯讀模式不實測（標 INFO；需 functional 測試才驗得到）。

> 狀態：`PASS` 通過、`FAIL` 失敗、`WARN` 建議改善、`SKIP` 不適用、`INFO` 參考資訊。

---

## CI 範例（GitHub Actions）

```yaml
- name: MCP conformance
  run: |
    pip install mcp jsonschema httpx
    python -m mcp_test "$MCP_URL" \
      --header "CF-Access-Client-Id: $CF_ID" \
      --header "CF-Access-Client-Secret: $CF_SECRET" \
      --strict
  env:
    MCP_URL: https://my-mcp.example.com/mcp
    CF_ID: ${{ secrets.MYMCP_CF_CLIENT_ID }}
    CF_SECRET: ${{ secrets.MYMCP_CF_CLIENT_SECRET }}
```

---

## 範圍與限制
- **唯讀**：只做 `list/describe/initialize` 與協定層負向，**不呼叫業務工具**，所以驗不到工具的實際輸出、async job 全流程、`/files` 真正下載。那些屬「functional 測試」（之後可擴充：吃一份 `mcp-test.json` 工具→參數→預期）。
- 適用三種：依 `REMOTE_MCP_SERVER_GUIDE.md` 建的 remote（公開 Streamable HTTP，帶 token）、本 repo 容器化的內網 Streamable HTTP（如 `http://badminton-db:8801/mcp`，無 auth）、以及本地 stdio。內網 MCP 沒有 Cloudflare Access，所以「未帶 token 被擋」那條 WARN 不適用（可忽略／`SKIP`）。

## 參考
- 建 server：`REMOTE_MCP_SERVER_GUIDE.md`、`ADD_NEW_MCP.md`
- 連線設定：`reels_mcp_usage.md`
