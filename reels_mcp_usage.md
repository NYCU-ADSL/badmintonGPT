nanobot（badmintonGPT 端）設定 — ~/.nanobot/config.json：

  {
    "mcpServers": {
      "badminton-reels": {
        "type": "http",
        "url": "https://reels-mcp.nycu-adsl.cc/mcp",
        "headers": {
          "CF-Access-Client-Id": "${REELS_CF_CLIENT_ID}",
          "CF-Access-Client-Secret": "${REELS_CF_CLIENT_SECRET}"
        }
      }
    }
  }

  REELS_CF_CLIENT_ID and REELS_CF_CLIENT_SECRET is in .env
  （每個 remote MCP 各用一組 ${<NAME>_CF_CLIENT_ID/SECRET}，見 .env.example）