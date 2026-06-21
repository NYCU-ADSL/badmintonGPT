---
name: data-analysis
description: >-
  需要對資料做「分析／統計／計算」時的 playbook：平均、中位數、分布、勝率、占比、相關、排名、
  彙總、交叉比較等。固定流程是先用 badminton-db MCP 取得原始資料，再用 exec 直接跑
  python3 -c（標準庫，無 pandas/numpy）做計算，最後才畫圖（visualise skill）或輸出表格。凡是會
  牽涉數字計算的問題都先讀本 skill，絕不心算或編造數字。
---

# data-analysis playbook（先算再畫）

任何需要計算的數據問題，順序固定：**取數 → 用 Python 算 → 呈現**。
不要省略中間的 Python 計算，也不要在腦中硬算或猜數字。

## 環境（先知道）
- 容器內有 `python3`（3.12）。exec 在 **bwrap 沙箱 + 限定 workspace** 下執行。
- 可用：Python **標準庫**——
  `statistics`（mean / median / mode / pstdev / stdev / quantiles / correlation /
  linear_regression）、`collections`（Counter / defaultdict）、`math`、`itertools`、
  `json`、`csv`。
- **不可用**：`pandas` / `numpy` / `matplotlib` / `scipy`（沒安裝）。**不要 import、也不要
  `pip install`**——沙箱裝不起來，只會浪費回合。一般羽球統計用標準庫就夠。
- exec **連不到資料庫**（沙箱 + 本來就該走 MCP）。資料一律先用 badminton-db MCP 取得。

## 流程
1. **取數**：依 **badminton-db** skill 用 MCP `query` 拿到 rows（單句 SELECT，務必含
   `match_name` 篩特定比賽）。
2. **算**：用 `exec` **直接跑 `python3 -c "..."`**，把上一步的 rows 當 Python literal
   內嵌——**不要先 `write_file` 寫 .py 檔、也不要 echo/heredoc**。只用標準庫。
   - 外層命令用單引號包：`python3 -c '...'`；Python 內所有字串用**雙引號** `"..."`，
     才不會跟外層單引號打架（中文 enum 沒有單引號，安全）。
   - 腳本只 **`print` 精簡結果**（JSON 或小表），不要 dump 原始資料（exec 輸出 >10000 字截斷）。
3. **呈現**：用 Python 算出的數字——
   - 要圖 → 依 **visualise** skill 把成品包在 visualizer code fence（Chart.js / SVG，
     **不是** matplotlib 產的 PNG）。
   - 要表 → 直接輸出 markdown 表格。

## 鐵則
- **直接執行 `python3 -c`，不寫檔**；數字**一律由 Python 算**，回覆裡每個統計值都要對得上
  腳本 `print` 出來的結果。
- 圖一律用 **visualise** skill 畫（HTML / SVG，內嵌對話），**不要**用 Python 產圖檔
  （容器無 matplotlib，且圖要能在 WebUI 內嵌）。
- 標準庫解決即可；真的需要 pandas / numpy，請改在 image 安裝（告知使用者），別在 exec 裡硬裝。

## 範例：某選手各球種使用占比 → 長條圖
1. MCP 取數（badminton-db）：
   ```sql
   SELECT type, COUNT(*) n FROM shots
   WHERE match_name='<matches.name>' AND player='A' GROUP BY type ORDER BY n DESC;
   ```
2. 把回傳的 rows 內嵌，`exec` 直接跑（command 值如下）：
   ```bash
   python3 -c '
   import json
   rows = [{"type": "殺球", "n": 42}, {"type": "挑球", "n": 31}]  # ← MCP 回傳的 rows
   total = sum(r["n"] for r in rows)
   dist = [{"type": r["type"], "n": r["n"], "pct": round(100 * r["n"] / total, 1)} for r in rows]
   print(json.dumps({"total": total, "dist": dist}, ensure_ascii=False))
   '
   ```
3. 取得含 `pct` 的 `dist` → 依 **visualise** skill 畫長條圖，或輸出 markdown 表。

## 範例：每回合拍數分布（描述統計）
```bash
python3 -c '
import json, statistics as st
spr = [12, 8, 21, 5, 33, 9]  # ← 由 MCP 查每回合拍數後內嵌
print(json.dumps({
    "n_rallies": len(spr),
    "mean": round(st.mean(spr), 1),
    "median": st.median(spr),
    "max": max(spr),
    "p90": round(st.quantiles(spr, n=10)[-1], 1),
}, ensure_ascii=False))
'
```
拿到結果後依需求畫直方圖（visualise skill）或輸出表格。
