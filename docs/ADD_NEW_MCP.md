# 如何新增一個 MCP（BadmintonGPT）

本文件說明如何替 BadmintonGPT 的 nanobot agent 新增一個 MCP server。參考既有三例：
- `mcps/badminton-db/server.py` — **自有容器 + Streamable HTTP** MCP（`badminton-db`，**這是預設範式**）
- `mcps/util/server.py` — **本地 stdio** MCP（`util`，極小的 in-process 小工具）
- 遠端 `badminton-reels` — **remote Streamable HTTP** MCP（規格見 `REELS_MCP_HANDOFF.md`）

架構慣例：**MCP = 存取層（工具）、skill = playbook（怎麼用）**。新增 MCP 通常 = 寫 server + 在 nanobot 註冊（+ 選配一個 skill playbook）。

本 repo 自己的 MCP 都放在 `mcps/<name>/`，每個都自包含（self-contained）。

> **與 `REMOTE_MCP_SERVER_GUIDE.md` 的分工**：本文件聚焦「把一個 MCP 接進**這個 repo** 的 nanobot
> agent」（自有容器 HTTP / 本地 stdio / 寫 skill / 在 `nanobot/config.json` 註冊）。若你要的是「**從零**
> 打造一個對外的 **remote** MCP server 並部署上線」的完整教學（含 `example-mcp-server/` 範例、
> Cloudflare 部署、發佈成公開 docs 站），看 [`REMOTE_MCP_SERVER_GUIDE.md`](./REMOTE_MCP_SERVER_GUIDE.md)。

---

## 0. 先決定：自有容器 HTTP、本地 stdio、還是 remote HTTP？

| | 自有容器 + Streamable HTTP（**預設**） | 本地 stdio | remote Streamable HTTP |
|---|---|---|---|
| 何時用 | 本 repo 內**多數** MCP（有狀態/相依、要健康檢查、要與 gateway 解耦） | **極小的 in-process 小工具**（無相依、純 stdlib，如 `util` 的 `sleep`） | 重任務/長時間（影片、GPU）、或本來就跑在別機/別 repo 的服務 |
| 跑在哪 | compose 上**自己的容器**（compose 內網，不對外） | 由 gateway in-process spawn（不是獨立容器） | 別處常駐 + 對外（Cloudflare Tunnel + Access） |
| nanobot 設定 | `type:"streamableHttp"` + `url: http://<service>:<port>/mcp`（**內網無 auth**） | `command` + `args` + `env` | `type:"streamableHttp"` + `url`（公開）+ `headers` |
| 範例 | `badminton-db`（`mcps/badminton-db/`，service `badminton-db`，:8801/mcp） | `util`（`mcps/util/`，stdio） | `badminton-reels`（`reels-mcp.nycu-adsl.cc`） |

預設選 **自有容器 + Streamable HTTP**（鏡像 `mcps/badminton-db/`）：each MCP = 自己的容器，gateway 透過 compose 內網的 `http://<service>:<port>/mcp` 連，內網不需 auth。
- 只有「**極小、無相依的 in-process 小工具**」才用 **本地 stdio**（鏡像 `mcps/util/`，由 gateway 直接 spawn，不另開容器）。
- 只有「本來就跑在別機/別 repo、要公開」的服務才走 **remote HTTP**（流程見 `REELS_MCP_HANDOFF.md`）。

---

## 1. 自有容器 + Streamable HTTP MCP（預設範式）

完整可照抄的範本就是 `mcps/badminton-db/`。一個 MCP = 一個 `mcps/<name>/` 目錄（server + 自己的 Dockerfile + 一個 compose service）。

### 1.1 寫 server（FastMCP + streamable-http + /healthz）
放在新目錄 `mcps/<name>/server.py`。只依賴 `mcp` + 你需要的套件 + stdlib。範本（鏡像 `mcps/badminton-db/server.py`）：

```python
#!/usr/bin/env python3
"""<name> — streamable-http MCP（自有容器）。Tools: ...
Transport (env MCP_TRANSPORT): "streamable-http"（預設，掛在 MCP_HOST:MCP_PORT 的 /mcp）
或 "stdio"（給 smoke test 用）。
Env: MCP_HOST (default 0.0.0.0), MCP_PORT (e.g. 8802), <你需要的其它>。
"""
from __future__ import annotations
import os
from typing import Annotated
from mcp.server.fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

mcp = FastMCP(                       # 這個名字會出現在 nanobot 工具前綴
    "<name>",
    host=os.environ.get("MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_PORT", "8802")),   # 每個 MCP 用不同 port（db=8801）
)

@mcp.tool()
def my_tool(
    arg: Annotated[str, Field(description="這個參數是什麼、格式/範例（agent 會在 schema 看到）。")],
) -> dict:
    """一句話描述工具用途與輸入（LLM 會讀這段 docstring 決定何時呼叫）。"""
    # ... 做事，回傳 JSON-able 的 dict / list / 純值
    return {"result": arg.upper()}

@mcp.custom_route("/healthz", methods=["GET"])   # 容器 healthcheck 用，不碰資料
async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})

def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    if transport == "stdio":
        mcp.run()                              # stdio（給 smoke test）
    else:
        mcp.run(transport="streamable-http")   # MCP endpoint 掛在 /mcp

if __name__ == "__main__":
    main()
```

慣例（沿用 `mcps/badminton-db/server.py`）：
- **streamable-http 為主、stdio 為備**：預設 `mcp.run(transport="streamable-http")`，並支援 `MCP_TRANSPORT=stdio` 讓 smoke test 不必開 HTTP server。
- **一定加 `GET /healthz`**（`@mcp.custom_route`，不碰資料）：容器 healthcheck 用它，compose 的 `depends_on: service_healthy` 才有依據。
- **唯讀/安全**：若碰資料庫，用 `sqlite3.connect("file:...?mode=ro", uri=True)` + 只允許 SELECT（正則擋多句/非 SELECT）。對外輸入做白名單驗證。
- **回傳結構化**：回 `dict`/`list`，FastMCP 會包成 structured content；錯誤回 `{"error": "..."}` 而非 raise（讓 agent 看得到原因）。
- **工具命名**：用清楚動詞（`list_*`/`get_*`/`find_*`/`generate_*`）。docstring 寫清楚「何時用」。
- **每個參數加描述**：docstring 只會變成「工具」層級的描述，FastMCP **不會**把 docstring 的 `Args:` 拆給各參數。要讓 agent 在 `inputSchema` 看到每個參數的說明，用 `Annotated[T, Field(description="...")]`（預設值放在 `Annotated` 外面：`x: Annotated[int, Field(description="...")] = 8`）。`Field` 也能帶 `ge`/`le`/`pattern` 等驗證 —— 但那會「拒絕」超界值，若你本來是想**靜默 clamp**就只寫 `description`，把界限寫進文字。
- **self-contained**：相依的 lib／資料儘量 vendored 進 `mcps/<name>/`（鏡像 `mcps/badminton-db/ingest_lib/`），不要跨 repo `sys.path` 注入，讓它自己一個 Dockerfile 就能 build。

### 1.2 寫 per-MCP Dockerfile
在 `mcps/<name>/Dockerfile`（build context = 該目錄，鏡像 `mcps/badminton-db/Dockerfile`）：

```dockerfile
# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
RUN uv pip install --system --no-cache "mcp>=1.0" <你需要的其它套件>
WORKDIR /app
COPY . /app
RUN useradd -m -u 1000 -s /bin/bash app && chown -R app:app /app
USER app
ENV MCP_HOST=0.0.0.0 MCP_PORT=8802 MCP_TRANSPORT=streamable-http
EXPOSE 8802
# slim image 沒 curl，用 stdlib urllib 打 /healthz
HEALTHCHECK --interval=30s --timeout=5s --retries=5 --start-period=10s \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8802/healthz', timeout=3).status==200 else 1)"
CMD ["python3", "/app/server.py"]
```

### 1.3 加一個 compose service
在 `docker-compose.yml` 加一個 service（鏡像 `badminton-db` service）：build context 指向 `./mcps/<name>`、掛你需要的 volume、加 `healthcheck`（打 `/healthz`）、**不要 publish host port**（只在 compose 內網），並讓 `gateway` 在 `depends_on` 加 `{<name>: {condition: service_healthy}}`：

```yaml
  <name>:
    build:
      context: ./mcps/<name>
    image: badmintongpt-<name>:0.1.0
    restart: unless-stopped
    networks: [default]
    expose: ["8802"]                 # 只在 compose 內網（不要 ports:）
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8802/healthz', timeout=3).status==200 else 1)"]
      interval: 30s
      timeout: 5s
      retries: 5
```

### 1.4 註冊到 nanobot
編輯 `nanobot/config.json`（canonical 範本）的 **`tools.mcpServers`**（注意：在 `tools` 底下，不是頂層）。容器內網用 service 名當 host，**不需 auth**：

```jsonc
"mcpServers": {
  "<name>": {
    "type": "streamableHttp",
    "url": "http://<name>:8802/mcp",   // compose service 名 + port + /mcp（內網，無 auth）
    "enabledTools": ["my_tool"]        // 只註冊這些工具；省略=全部
  }
}
```
- compose 內網不需要 `headers`／token（**絕不對外 publish、絕不 tunnel**）。
- HOST/DEV 模式（不跑容器）：把 server 當本地 HTTP 跑（`MCP_HOST=127.0.0.1 MCP_PORT=8802 python mcps/<name>/server.py`），`~/.nanobot/config.json` 改指 `http://127.0.0.1:8802/mcp`。

### 1.5 載入 + 測試
```bash
# (a) 先獨立 smoke test（不經 nanobot）— 仿 mcps/badminton-db/scripts/test_db_mcp.py
#     用 MCP_TRANSPORT=stdio 開 stdio session，免開 HTTP server
.venv/bin/python mcps/badminton-db/scripts/test_db_mcp.py   # 改成指向你的 server / 工具

# (b) build + 起容器，讓 gateway 連新 MCP
docker compose up -d --build
docker compose logs gateway | grep "MCP server '<name>'"     # 應見 connected

# (c) 直接打 HTTP 端點驗收（compose 內網或 host，見 MCP_TEST.md）
.venv/bin/python -m mcp_test http://<name>:8802/mcp          # 或 http://127.0.0.1:8802/mcp（host 模式）
```
獨立測試骨架（改 `mcps/badminton-db/scripts/test_db_mcp.py`）：用 `MCP_TRANSPORT=stdio` 開 `StdioServerParameters` → `ClientSession` → `list_tools()` / `call_tool("my_tool", {...})`。

---

## 2. 本地 stdio MCP（只給極小的 in-process 小工具）

只有「**極小、無相依、純 stdlib** 的 in-process 小工具」才用這條（鏡像 `mcps/util/`，唯一工具是 `sleep`）。它不開自己的容器，由 gateway 直接 spawn。

### 2.1 寫 server
放在 `mcps/<name>/server.py`。最精簡（無 HTTP、無 /healthz）：

```python
#!/usr/bin/env python3
"""<name> — local stdio MCP（in-process 小工具）。Tools: ..."""
from typing import Annotated
from mcp.server.fastmcp import FastMCP
from pydantic import Field
mcp = FastMCP("<name>")

@mcp.tool()
def my_tool(
    arg: Annotated[str, Field(description="這個參數是什麼、格式/範例。")],
) -> dict:
    """一句話描述工具用途與輸入。"""
    return {"result": arg.upper()}

if __name__ == "__main__":
    mcp.run()   # stdio transport
```

### 2.2 註冊到 nanobot（stdio，鏡像 `util`）
```jsonc
"mcpServers": {
  "<name>": {
    "type": "stdio",
    "command": "python3",
    "args": ["/app/mcps/<name>/server.py"],   // 容器內路徑（gateway image 有 COPY mcps/<name>/）
    "enabledTools": ["my_tool"],
    "toolTimeout": 70                          // 若工具會阻塞（如 sleep）要拉長
  }
}
```
- 容器模式下 gateway image 需 `COPY mcps/<name>/`（鏡像 util）；HOST/DEV 模式 `command` 改本 repo `.venv` 的 python 絕對路徑、`args` 改本機絕對路徑。
- stdio 小工具不另開 compose service、不需 healthcheck。

---

## 3. remote HTTP MCP（別機/別 repo、要公開）

只有「本來就跑在別機/別 repo、要公開」的服務才走這條（如 `badminton-reels`）。完整流程見 `REELS_MCP_HANDOFF.md`，重點：
1. server 用 FastMCP 的 **Streamable HTTP**：`mcp.run(transport="streamable-http")`，bind `127.0.0.1:<port>`。
2. 對外用 **Cloudflare Tunnel**（加一條 ingress → `http://127.0.0.1:<port>`）+ **Access service token** 驗證。
3. nanobot 註冊（公開 URL，**要帶 token headers**，跟 §1 的內網 HTTP 不同）：
```jsonc
"mcpServers": {
  "<name>": {
    "type": "streamableHttp",
    "url": "https://<name>.nycu-adsl.cc/mcp",
    "headers": {
      "CF-Access-Client-Id": "${<NAME>_CF_CLIENT_ID}",
      "CF-Access-Client-Secret": "${<NAME>_CF_CLIENT_SECRET}"
    },
    "toolTimeout": 120,
    "enabledTools": ["..."]
  }
}
```
4. 長任務一律走「**非同步 job**」模式：`start_*` 回 `job_id` → `get_*_status` 輪詢 → `get_*_result`（見 reels）。

---

## 4.（建議）加一個 skill playbook

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

## 5. 檢查清單（每次新增 MCP）

- [ ] MCP 放在 `mcps/<name>/` 且 self-contained（相依 lib/資料 vendored，不跨 repo 注入）。
- [ ] **預設範式（自有容器 HTTP）**：server 有 `mcp.run(transport="streamable-http")` + `GET /healthz` + `MCP_TRANSPORT=stdio` 備援；有 per-MCP `Dockerfile`；`docker-compose.yml` 加了 service（`expose` 不 `ports`、有 healthcheck）；`gateway` 的 `depends_on` 加了 `{<name>: service_healthy}`。
- [ ]（stdio 小工具才需）確認真的極小無相依；gateway image 有 `COPY mcps/<name>/`；`toolTimeout` 視阻塞調整。
- [ ] `tools.mcpServers.<name>`：內網 HTTP 用 `streamableHttp` + `http://<name>:<port>/mcp`（**無 auth**）；stdio 用 `command: python3` + 容器內 `args`；remote 用 `streamableHttp` + 公開 url + token headers。
- [ ] `enabledTools` 設定要曝露的工具（最小化）。
- [ ] 機密只給 remote MCP 用 `${VAR}` + `scripts/load_env.sh`（**只讀本專案 `.env`，不退回其他專案**）；內網 MCP 不需 token。
- [ ] 獨立 smoke test 通過（`MCP_TRANSPORT=stdio`：list_tools / call_tool / 錯誤情境）。
- [ ] `docker compose up -d --build` 後 gateway log 顯示 `MCP server '<name>': connected`；HTTP 端點過 `python -m mcp_test http://<name>:<port>/mcp`。
- [ ]（選配）skill playbook 建好並 symlink 到 workspace；SOUL.md 路由補一行。
- [ ] 若是 read-only 部署：確認新工具不會破壞唯讀邊界（不寫使用者資料、無 shell）。
- [ ] 在 `eval/run_eval.py` 加一兩題驗收（預期呼叫到 `<name>` 的工具 + 答案正確）。

## 參考
- 自有容器 HTTP 範例（預設）：`mcps/badminton-db/`（`server.py`、`Dockerfile`、`scripts/test_db_mcp.py`）、`docker-compose.yml` 的 `badminton-db` service
- 本地 stdio 範例：`mcps/util/server.py`
- remote 範例與部署：`REELS_MCP_HANDOFF.md`、`reels_mcp_usage.md`
- 端點驗收：`MCP_TEST.md`（`python -m mcp_test`）
- 整體架構與 nanobot 設定事實：`DESIGN.md`、`CLAUDE.md`
