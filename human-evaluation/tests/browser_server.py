"""Isolated browser-test fixture; never published as the real evaluation dataset."""
import json
from pathlib import Path
import sys
import subprocess
import base64

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from server import create_app

runtime = HERE / "runtime/browser-test"
runtime.mkdir(parents=True, exist_ok=True)
media = runtime / "media/q001"
media.mkdir(parents=True, exist_ok=True)
(media / "fixture.png").write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="))
if not (media / "fixture.webm").exists():
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=0x287f63:s=320x180:d=1", "-c:v", "libvpx-vp9", "-an",
                    str(media / "fixture.webm")], check=True)
answer = """## Rendering test fixture

| Player | Points |
|---|---:|
| A | 12 |
| B | 10 |

The ratio is:

$$12/22$$

```python
points = 12
```

```visualizer
<div style="padding:20px;font-family:sans-serif"><h3>Interactive chart fixture</h3><button onclick="this.textContent='Selected'">Select player A</button><svg width="260" height="90"><rect width="220" height="22" y="10" fill="#287f63"/><rect width="180" height="22" y="45" fill="#aac59b"/></svg></div>
```

![fixture.png](/api/media/q001/fixture.png)

![fixture.webm](/api/media/q001/fixture.webm)
"""
answer += "\n\nLong URL returned as inline code:\n\n`https://video.example.test/files/" + "a" * 250 + "`\n"
path = runtime / "dataset.json"
path.write_text(json.dumps({"id": "browser-fixture", "model": "fixture", "target_count": 2, "items": [
    {"id": "q001", "query_en": "In this test fixture, compare the players’ scoring patterns and show a chart.",
     "query_zh_tw": "在這份測試資料中，比較兩位球員的得分模式，並用圖表呈現。", "answer": answer,
     "output_messages": [{"text": answer, "media_urls": []}]},
    {"id": "q002", "query_en": "Second browser test question.", "query_zh_tw": "第二道瀏覽器測試問題。", "answer": "Second fixture answer."}
]}))
app = create_app(path, runtime / "ratings.sqlite3", HERE / "web/dist")
