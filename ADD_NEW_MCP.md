# 如何新增一個 MCP（BadmintonGPT）

本文件說明如何替 BadmintonGPT 的 nanobot agent 新增一個 MCP server。參考既有兩例：
- `db_mcp/server.py` — **本地 stdio** MCP（`badminton-db`）
- 遠端 `badminton-reels` — **remote Streamable HTTP** MCP（規格見 `REELS_MCP_HANDOFF.md`）

架構慣例：**MCP = 存取層（工具）、skill = playbook（怎麼用）**。新增 MCP 通常 = 寫 server + 在 nanobot 註冊（+ 選配一個 skill playbook）。

---

## 0. 先決定：本地 stdio 還是 remote HTTP？

| | 本地 stdio | remote Streamable HTTP |
|---|---|---|
| 何時用 | 跑在同一台、輕量、純讀資料/計算（如查 SQLite） | 重任務/長時間（影片、GPU）、或要跨機/獨立部署、或本來就是別的服務 |
| nanobot 設定 | `command` + `args` + `env` | `type:"streamableHttp"` + `url` + `headers` |
| 啟動 | 由 nanobot 自動 spawn（不必自己常駐） | 自己常駐 + 對外（建議 Cloudflare Tunnel + Access） |
| 範例 | `badminton-db` | `badminton-reels` |

預設選 **本地 stdio**（最省事）。只有「重/長/跨機」才走 remote（流程見 `REELS_MCP_HANDOFF.md`）。

---

## 1. 本地 stdio MCP（最常用）

### 1.1 寫 server
放在新目錄 `<name>_mcp/server.py`。只依賴 `mcp`（已在 `.venv`）+ stdlib。範本：

```python
#!/usr/bin/env python3
"""<name> — local stdio MCP. Tools: ...
Env: <whatever you need, e.g. BADMINTON_DB>
"""
from __future__ import annotations
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("<name>")          # 這個名字會出現在 nanobot 工具前綴

@mcp.tool()
def my_tool(arg: str) -> dict:
    """一句話描述工具用途與輸入（LLM 會讀這段 docstring 決定何時呼叫）。"""
    # ... 做事，回傳 JSON-able 的 dict / list / 純值
    return {"result": arg.upper()}

def main() -> None:
    mcp.run()                    # stdio transport

if __name__ == "__main__":
    main()
```

慣例（沿用 `db_mcp/server.py`）：
- **唯讀/安全**：若碰資料庫，用 `sqlite3.connect("file:...?mode=ro", uri=True)` + 只允許 SELECT（正則擋多句/非 SELECT）。對外輸入做白名單驗證。
- **回傳結構化**：回 `dict`/`list`，FastMCP 會包成 structured content；錯誤回 `{"error": "..."}` 而非 raise（讓 agent 看得到原因）。
- **工具命名**：用清楚動詞（`list_*`/`get_*`/`find_*`/`generate_*`）。docstring 寫清楚「何時用」。

### 1.2 註冊到 nanobot
編輯 `~/.nanobot/config.json` 的 **`tools.mcpServers`**（注意：在 `tools` 底下，不是頂層）：

```jsonc
"mcpServers": {
  "<name>": {
    "type": "stdio",
    "command": "/mnt/ssd1/howchien/badmintonGPT/.venv/bin/python",   // ⚠️ 必須是這個 venv 的絕對路徑（系統 python 沒有 mcp）
    "args": ["/mnt/ssd1/howchien/badmintonGPT/<name>_mcp/server.py"],
    "env": { "SOME_VAR": "/abs/path/or/${ENV_VAR}" },
    "enabledTools": ["my_tool"]      // 只註冊這些工具；省略=全部
  }
}
```
- `command` 用 **`.venv/bin/python` 絕對路徑**（最常踩的雷）。
- `env` 可硬編絕對路徑，或用 `${VAR}`（nanobot 啟動時從環境解析；該 VAR 要在 `nanobot gateway` 前 export，見 `scripts/load_env.sh`）。

### 1.3 載入 + 測試
```bash
# (a) 先獨立 smoke test（不經 nanobot）— 仿 scripts/test_db_mcp.py
.venv/bin/python scripts/test_db_mcp.py        # 改成指向你的 server / 工具

# (b) 重啟 gateway 讓它連新 MCP
source scripts/load_env.sh
pkill -x nanobot 2>/dev/null; nanobot gateway   # 注意：pkill 用 -x nanobot，別用 -f（會誤殺自己）
# 在 log 找： MCP server '<name>': connected, N capabilities registered
```
獨立測試骨架（改 `scripts/test_db_mcp.py`）：開 `StdioServerParameters(command=venv_python, args=[server.py], env=...)` → `ClientSession` → `list_tools()` / `call_tool("my_tool", {...})`。

---

## 2. remote HTTP MCP（重/長/跨機）

完整流程見 `REELS_MCP_HANDOFF.md`，重點：
1. server 用 FastMCP 的 **Streamable HTTP**：`mcp.run(transport="streamable-http")`，bind `127.0.0.1:<port>`。
2. 對外用 **Cloudflare Tunnel**（加一條 ingress → `http://127.0.0.1:<port>`）+ **Access service token** 驗證。
3. nanobot 註冊：
```jsonc
"mcpServers": {
  "<name>": {
    "type": "streamableHttp",
    "url": "https://<name>.nycu-adsl.cc/mcp",
    "headers": {
      "CF-Access-Client-Id": "${CF_ACCESS_CLIENT_ID}",
      "CF-Access-Client-Secret": "${CF_ACCESS_CLIENT_SECRET}"
    },
    "toolTimeout": 120,
    "enabledTools": ["..."]
  }
}
```
4. 長任務一律走「**非同步 job**」模式：`start_*` 回 `job_id` → `get_*_status` 輪詢 → `get_*_result`（見 reels）。

---

## 3.（建議）加一個 skill playbook

MCP 提供「能力」；skill 提供「怎麼用得好」(何時觸發、慣例、範例)。沿用 `skills/badminton-db/`、`skills/badminton-reels/`：

```
skills/<name>/
└── SKILL.md            # frontmatter: name + description(務必寫清楚觸發時機)；body: 用法/範例/慣例
    references/         # 選配：enum、schema 等「觸發後才載入」的細節
```

接上 nanobot（skill 探索路徑是 `~/.nanobot/workspace/skills/`）：
```bash
ln -sfn "$PWD/skills/<name>" ~/.nanobot/workspace/skills/<name>
```
並在 `~/.nanobot/workspace/SOUL.md` 的「工具路由」補一行：什麼問題 → 用 `<name>` skill / MCP 工具。

> 注意：skill 是**啟發式觸發**（靠 description），不保證一定載入；但 MCP 工具恆在，agent 仍可直接呼叫。關鍵慣例（例如唯讀規則、必填篩選）最好也寫進 SOUL.md（always-loaded）以防漏觸發。

---

## 4. 檢查清單（每次新增 MCP）

- [ ] server 只依賴 `.venv` 有的套件（`mcp` + 你需要的）；資料工具做唯讀/輸入驗證。
- [ ] `tools.mcpServers.<name>`：stdio 用 **venv 絕對 python**；remote 用 `streamableHttp`+url+headers。
- [ ] `enabledTools` 設定要曝露的工具（最小化）。
- [ ] 機密用 `${VAR}` + `scripts/load_env.sh`（**只讀本專案 `.env`，不退回其他專案**）。
- [ ] 獨立 smoke test 通過（list_tools / call_tool / 錯誤情境）。
- [ ] `nanobot gateway` log 顯示 `MCP server '<name>': connected`。
- [ ]（選配）skill playbook 建好並 symlink 到 workspace；SOUL.md 路由補一行。
- [ ] 若是 read-only 部署：確認新工具不會破壞唯讀邊界（不寫使用者資料、無 shell）。
- [ ] 在 `eval/run_eval.py` 加一兩題驗收（預期呼叫到 `<name>` 的工具 + 答案正確）。

## 參考
- 本地 stdio 範例：`db_mcp/server.py`、`scripts/test_db_mcp.py`
- remote 範例與部署：`REELS_MCP_HANDOFF.md`、`reels_mcp_usage.md`
- 整體架構與 nanobot 設定事實：`DESIGN.md`、`CLAUDE.md`
