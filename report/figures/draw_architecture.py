"""Render the high-level BadmintonGPT architecture as PDF, SVG, and PNG."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


OUT = Path(__file__).resolve().parent
plt.rcParams.update({
    "font.family": "DejaVu Serif",
    "font.size": 11,
    "pdf.fonttype": 42,
    "svg.fonttype": "none",
})
fig, ax = plt.subplots(figsize=(12, 7.25))
fig.subplots_adjust(left=0.015, right=0.985, bottom=0.02, top=0.98)
ax.set(xlim=(0, 12), ylim=(0, 7.25))
ax.axis("off")
INK = "#28333D"
MUTED = "#52606A"
BLUE = "#EAF0F6"
GREEN = "#EDF3EE"
GREY = "#F5F5F3"


def label(x, y, s, size=11, weight="normal", color=INK, **kw):
    return ax.text(x, y, s, ha="center", va="center", fontsize=size,
                   fontweight=weight, color=color, **kw)


def box(x, y, w, h, fill="white", edge=INK, lw=1.05):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=0.045",
        facecolor=fill, edgecolor=edge, linewidth=lw, zorder=2,
    ))


def arrow(a, b, both=False):
    ax.add_patch(FancyArrowPatch(
        a, b, arrowstyle="<->" if both else "->", mutation_scale=11,
        linewidth=1.05, color=MUTED, shrinkA=1.5, shrinkB=1.5, zorder=3,
    ))


def line(a, b):
    ax.plot([a[0], b[0]], [a[1], b[1]], color=MUTED, lw=1.05, zorder=1)


label(6, 7.0, "Coaches  ·  Players  ·  Fans", size=12)
arrow((6, 6.8), (6, 6.48), both=True)
box(2.45, 5.65, 7.1, 0.82, GREY)
label(6, 6.2, "Conversational interface", size=13, weight="bold")
label(6, 5.88, "Natural-language requests  /  Text, charts, and video", size=11)

arrow((5.30, 5.64), (5.30, 5.03))
arrow((6.70, 5.03), (6.70, 5.64))
label(4.45, 5.34, "Requests", size=9.5, color=MUTED)
label(7.62, 5.34, "Responses", size=9.5, color=MUTED)

box(1.4, 3.62, 9.2, 1.4, BLUE)
label(6, 4.74, "BadmintonGPT · LLM agent", size=15, weight="bold")
label(6, 4.37, "Understand intent   →   Select capabilities   →   Synthesize results", size=11.5)
box(3.35, 3.79, 5.3, 0.34, "white", edge="#8497AA", lw=0.8)
label(6, 3.96, "Domain skills & workflow playbooks", size=10.5)

arrow((6, 3.61), (6, 3.10), both=True)
label(8.23, 3.35, "Tool requests / results", size=9.5, color=MUTED)
centers = [1.28, 3.64, 6.0, 8.36, 10.72]
line((centers[0], 3.09), (centers[-1], 3.09))
capabilities = [
    ("Match data", "querying"),
    ("Tactical", "analysis"),
    ("Video", "retrieval"),
    ("Highlight", "generation"),
    ("Web", "search"),
]
for cx, (first, second) in zip(centers, capabilities):
    arrow((cx, 3.08), (cx, 2.60), both=True)
    box(cx - 1.06, 1.81, 2.12, 0.78, GREEN)
    label(cx, 2.20, first + "\n" + second, size=12, weight="bold", linespacing=1.4)

# The first four capabilities are MCP integrations; web search is built in.
line((0.22, 1.65), (9.42, 1.65))
line((0.22, 1.65), (0.22, 1.74))
line((9.42, 1.65), (9.42, 1.74))
label(4.82, 1.45, "Badminton services", size=9.5, color=MUTED,
      bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.5})

resources = [
    (0.22, 2.12, "Match records\n& shot annotations"),
    (2.58, 2.12, "Match analysis\ndata"),
    (4.94, 4.48, "Match videos & rally clips"),
    (9.66, 2.12, "External\ninformation"),
]
for x, w, name in resources:
    box(x, 0.30, w, 0.73, GREY, edge="#7A8288", lw=0.85)
    label(x + w / 2, 0.665, name, size=10.5, linespacing=1.4)
for cx in centers:
    arrow((cx, 1.04), (cx, 1.80))

for ext in ("pdf", "svg", "png"):
    fig.savefig(OUT / f"badmintongpt_architecture.{ext}", dpi=300,
                facecolor="white", metadata={"Creator": "BadmintonGPT architecture figure"})
plt.close(fig)
print("Created PDF, SVG, and 300 dpi PNG in", OUT)
