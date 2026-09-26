"""Build the editable overview diagram and its publication-ready exports.

The source layout is shared by the PDF, SVG, PNG, and draw.io versions.
Run ``python paper/figures/make_overview.py`` from the repository root.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch


OUT = Path(__file__).resolve().parent
WIDTH, HEIGHT = 1200, 816
INK = "#2D3552"
MUTED = "#65708A"
LINE = "#CCD3E5"
PANEL = "#FBFAFD"
# Blue and violet palette; darker accents keep labels legible.
MID, LAVENDER = "#8B8FCA", "#B7AED9"
LAVENDER_TINT = "#E8E4F2"
BLUE, BLUE_BG = "#4C65A4", "#EEF1F9"
TEAL, TEAL_BG = "#6474AB", "#EEF0F8"
PURPLE, PURPLE_BG = "#7066A2", "#F1EEF8"
GREEN, GREEN_BG = BLUE, "#F0F1F9"
Y_SHIFT = 0
LOWER_SCALE = 0.90
LOWER_ANCHOR = 247

fig = plt.figure(figsize=(12, 8.16), dpi=160)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, WIDTH)
ax.set_ylim(HEIGHT, 0)
ax.set_aspect("equal")
ax.axis("off")
fig.patch.set_facecolor("white")

mxfile = ET.Element("mxfile", {"host": "app.diagrams.net", "agent": "MARSHAL paper", "type": "device"})
diagram = ET.SubElement(mxfile, "diagram", {"id": "overview", "name": "Overview"})
model = ET.SubElement(diagram, "mxGraphModel", {"dx": str(WIDTH), "dy": str(HEIGHT), "grid": "0", "page": "1", "pageScale": "1", "pageWidth": str(WIDTH), "pageHeight": str(HEIGHT), "math": "0", "shadow": "0"})
root = ET.SubElement(model, "root")
ET.SubElement(root, "mxCell", {"id": "0"})
ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
next_id = 2


def cell_id() -> str:
    global next_id
    value = str(next_id)
    next_id += 1
    return value


def vertex(x: float, y: float, w: float, h: float, style: str, value: str = "") -> None:
    cell = ET.SubElement(root, "mxCell", {"id": cell_id(), "parent": "1", "vertex": "1", "style": style, "value": value})
    ET.SubElement(cell, "mxGeometry", {"x": str(x), "y": str(y), "width": str(w), "height": str(h), "as": "geometry"})


def mapped_y(y: float) -> float:
    if not Y_SHIFT:
        return y
    return LOWER_ANCHOR + Y_SHIFT + LOWER_SCALE * (y - LOWER_ANCHOR)


def rect(x: float, y: float, w: float, h: float, *, fill: str = "white", stroke: str = LINE, radius: float = 12, lw: float = 1.5, dash: bool = False, zorder: float = 1) -> None:
    y = mapped_y(y)
    if Y_SHIFT:
        h *= LOWER_SCALE
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={radius}", facecolor=fill, edgecolor=stroke, linewidth=lw, linestyle="--" if dash else "-", zorder=zorder))
    arc = max(3, int(100 * radius / max(1, min(w, h))))
    vertex(x, y, w, h, f"rounded=1;arcSize={arc};whiteSpace=wrap;html=0;fillColor={fill};strokeColor={stroke};strokeWidth={lw};dashed={int(dash)};")


def disk(cx: float, cy: float, r: float, *, fill: str, stroke: str, lw: float = 1.5, zorder: float = 4) -> None:
    cy = mapped_y(cy)
    ax.add_patch(Circle((cx, cy), r, facecolor=fill, edgecolor=stroke, linewidth=lw, zorder=zorder))
    vertex(cx - r, cy - r, 2 * r, 2 * r, f"ellipse;html=0;fillColor={fill};strokeColor={stroke};strokeWidth={lw};")


def txt(x: float, y: float, value: str, *, size: float = 16, color: str = INK, bold: bool = False, ha: str = "center", width: float | None = None, height: float | None = None) -> None:
    y = mapped_y(y)
    ax.text(x, y, value, fontsize=size, color=color, fontweight="bold" if bold else "normal", ha=ha, va="center", family="DejaVu Sans", linespacing=1.12, zorder=6)
    lines = value.split("\n")
    width = width or max(24, max(map(len, lines)) * size * 0.64)
    height = height or max(19, len(lines) * size * 1.35)
    left = x if ha == "left" else x - width if ha == "right" else x - width / 2
    vertex(left, y - height / 2, width, height, f"text;html=0;whiteSpace=wrap;overflow=visible;fillColor=none;strokeColor=none;fontFamily=Helvetica;fontSize={size};fontColor={color};fontStyle={1 if bold else 0};align={ha};verticalAlign=middle;", value)


def line(points: list[tuple[float, float]], *, color: str = LINE, lw: float = 1.8, head: bool = False, dash: bool = False, zorder: float = 2) -> None:
    points = [(x, mapped_y(y)) for x, y in points]
    xs, ys = zip(*points)
    ax.plot(xs, ys, color=color, lw=lw, linestyle="--" if dash else "-", solid_capstyle="round", solid_joinstyle="round", zorder=zorder)
    if head:
        ax.add_patch(FancyArrowPatch(points[-2], points[-1], arrowstyle="-|>", mutation_scale=13, linewidth=lw, color=color, zorder=5))
    edge = ET.SubElement(root, "mxCell", {"id": cell_id(), "parent": "1", "edge": "1", "style": f"edgeStyle=none;html=0;strokeColor={color};strokeWidth={lw};dashed={int(dash)};endArrow={'block' if head else 'none'};endFill=1;"})
    geo = ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
    ET.SubElement(geo, "mxPoint", {"x": str(points[0][0]), "y": str(points[0][1]), "as": "sourcePoint"})
    ET.SubElement(geo, "mxPoint", {"x": str(points[-1][0]), "y": str(points[-1][1]), "as": "targetPoint"})
    if len(points) > 2:
        bends = ET.SubElement(geo, "Array", {"as": "points"})
        for x, y in points[1:-1]:
            ET.SubElement(bends, "mxPoint", {"x": str(x), "y": str(y)})


def panel_title(x: float, y: float, letter: str, title: str, color: str) -> None:
    txt(x + 30, y, title, size=19, bold=True, ha="left")


# A. A concrete three-agent scene occupies more space than the pipeline below.
# Partner A proposes a public goal to B while M observes, infers, plans, acts.
rect(20, 18, 1160, 310, fill=PANEL, stroke="#DCE5F3", radius=17, lw=1.5)


def avatar(cx: float, cy: float, label: str, color: str, bg: str, *, pale: bool = False) -> None:
    stroke = "#AEBBC7" if pale else color
    fill = "#F1F4F7" if pale else bg
    disk(cx, cy, 14, fill=fill, stroke=stroke, lw=1.5)
    txt(cx, cy, label, size=12, color=stroke, bold=True)


def thought_bubble(cx: float, cy: float, label: str, color: str, bg: str) -> None:
    rect(cx - 90, cy - 41, 180, 82, fill=bg, stroke=color, radius=12, lw=1.5, zorder=3)
    txt(cx, cy, label, size=12, color=INK, bold=True)


scene_cards = [(40, "Observe", BLUE, BLUE_BG), (330, "Infer", PURPLE, LAVENDER),
               (620, "Plan", TEAL, MID), (910, "Act", BLUE, LAVENDER)]
for idx, (x, title, color, bg) in enumerate(scene_cards, 1):
    rect(x, 39, 250, 244, fill="white", stroke="#C9D5E8", radius=13)
    disk(x + 27, 66, 13, fill=bg, stroke=color, lw=1.3)
    txt(x + 27, 66, str(idx), size=14, color=color, bold=True)
    txt(x + 49, 66, title, size=18, color=color, bold=True, ha="left")

# 1. A invites B to repair a bridge; M sees the offer.
x = 40
line([(x + 55, 214), (x + 195, 214)], color=BLUE, lw=1.8, head=True)
line([(x + 125, 186), (x + 125, 214)], color=BLUE, lw=1.8)
line([(x + 125, 214), (x + 125, 235)], color=BLUE, lw=1.2, dash=True)
thought_bubble(x + 125, 145, "Let's repair\nthe bridge\ntogether.", BLUE, BLUE_BG)
avatar(x + 40, 214, "A", PURPLE, PURPLE_BG)
avatar(x + 210, 214, "B", TEAL, TEAL_BG)
avatar(x + 125, 251, "M", BLUE, BLUE_BG)

# 2. M takes A's voluntary offer as evidence of A's preference.
x = 330
line([(x + 125, 186), (x + 125, 235)], color=PURPLE, lw=1.5, dash=True)
thought_bubble(x + 125, 145, "A very likely\nprefers to repair\nthe bridge.", PURPLE, PURPLE_BG)
avatar(x + 40, 214, "A", PURPLE, PURPLE_BG)
avatar(x + 210, 214, "B", TEAL, TEAL_BG, pale=True)
avatar(x + 125, 251, "M", BLUE, BLUE_BG)

# 3. M compares its own interest with the inferred interest of A.
x = 620
line([(x + 125, 186), (x + 125, 235)], color=TEAL, lw=1.5, dash=True)
thought_bubble(x + 125, 145, "I want the bridge\nrepaired too.\nLet's coordinate.", TEAL, "#E9EAF6")
avatar(x + 40, 214, "A", PURPLE, PURPLE_BG)
avatar(x + 210, 214, "B", TEAL, TEAL_BG, pale=True)
avatar(x + 125, 251, "M", BLUE, BLUE_BG)

# 4. M proposes collaboration to A, creating the next observation.
x = 910
line([(x + 55, 214), (x + 195, 214)], color=BLUE, lw=1.8, head=True)
line([(x + 125, 186), (x + 125, 214)], color=BLUE, lw=1.8)
thought_bubble(x + 125, 145, "I can help repair\nthe bridge. Shall\nwe team up?", BLUE, LAVENDER_TINT)
avatar(x + 40, 214, "M", BLUE, BLUE_BG)
avatar(x + 210, 214, "A", PURPLE, PURPLE_BG)
avatar(x + 125, 251, "B", TEAL, TEAL_BG, pale=True)

for x in (290, 580, 870):
    line([(x + 3, 160), (x + 35, 160)], color=BLUE, lw=2.0, head=True)
line([(1123, 283), (1123, 310), (692, 310)], color=PURPLE, lw=1.8)
line([(508, 310), (76, 310), (76, 284)], color=PURPLE, lw=1.8, head=True)
txt(600, 310, "interaction loop", size=14, color=PURPLE, bold=True)

# B. The full game tree, with three different contiguous slices on its paths.
Y_SHIFT = 103
rect(20, 247, 476, 490, fill=PANEL, stroke="#DDE6EE", radius=17)
panel_title(40, 278, "B", "Game tree and slices", PURPLE)
node = {
    "r": (258, 351), "a": (134, 413), "b": (382, 413),
    "aa": (73, 483), "ab": (195, 483), "ba": (320, 483), "bb": (443, 483),
    "aaa": (44, 565), "aab": (102, 565), "aba": (166, 565), "abb": (225, 565),
    "baa": (290, 565), "bab": (350, 565), "bba": (413, 565), "bbb": (471, 565),
}
edges = [
    ("r", "a"), ("r", "b"),
    ("a", "aa"), ("a", "ab"), ("b", "ba"), ("b", "bb"),
    ("aa", "aaa"), ("aa", "aab"), ("ab", "aba"), ("ab", "abb"),
    ("ba", "baa"), ("ba", "bab"), ("bb", "bba"), ("bb", "bbb"),
]
slices = {
    ("a", "ab"): TEAL, ("ab", "abb"): TEAL,
    ("b", "ba"): BLUE,
}
for src, dst in edges:
    color = slices.get((src, dst), "#BCC8D4")
    line([node[src], node[dst]], color=color, lw=4.0 if (src, dst) in slices else 1.8)
selected_nodes = {"aa": PURPLE, "a": TEAL, "ab": TEAL, "abb": TEAL, "b": BLUE, "ba": BLUE}
for name, (x, y) in node.items():
    accent = selected_nodes.get(name)
    radius = 9 if name == "aa" else 7 if name not in {"aaa", "aab", "aba", "abb", "baa", "bab", "bba", "bbb"} else 5.3
    disk(x, y, radius, fill=accent or "white", stroke=accent or "#9EAFBE", lw=1.5)
for x, y, label, color, bg in [(50, 605, "slice 1", PURPLE, PURPLE_BG), (201, 605, "slice 2", TEAL, TEAL_BG), (350, 605, "slice 3", BLUE, LAVENDER_TINT)]:
    rect(x - 31, y - 15, 84, 30, fill=bg, stroke=color, radius=9, lw=1.3)
    txt(x + 11, y, label, size=13, color=color, bold=True)
for x in (61, 212, 361):
    line([(x, 620), (x, 631)], color=PURPLE, lw=1.2)
line([(61, 631), (361, 631)], color=PURPLE, lw=1.2)
line([(258, 631), (258, 641)], color=PURPLE, lw=1.5, head=True)
rect(109, 642, 302, 67, fill="white", stroke=PURPLE, radius=12, lw=1.5)
disk(146, 675, 20, fill=PURPLE_BG, stroke=PURPLE, lw=1.3)
line([(146, 665), (136, 683)], color=PURPLE, lw=1.5, zorder=5)
line([(146, 665), (156, 683)], color=PURPLE, lw=1.5, zorder=5)
disk(146, 665, 3, fill=PURPLE, stroke=PURPLE, lw=0.8, zorder=6)
disk(136, 683, 3, fill=PURPLE, stroke=PURPLE, lw=0.8, zorder=6)
disk(156, 683, 3, fill=PURPLE, stroke=PURPLE, lw=0.8, zorder=6)
txt(274, 662, "Oracle solver", size=16, color=PURPLE, bold=True)
txt(274, 687, "solve each selected slice", size=12, color=MUTED)

# C. Direct action supervision and two separately generated capability labels.
rect(510, 247, 339, 490, fill=PANEL, stroke="#DDE6EE", radius=17)
panel_title(530, 278, "C", "Supervision", PURPLE)
txt(679, 304, "Oracle-labeled objectives", size=14, color=MUTED)
rect(529, 328, 300, 73, fill="white", stroke=BLUE, radius=11, lw=1.6)
rect(541, 343, 52, 43, fill=BLUE_BG, stroke="none", radius=9)
txt(567, 365, "O", size=17, color=BLUE, bold=True)
txt(710, 365, "What to do given\nthe current state?", size=16, color=INK)

rect(524, 419, 310, 207, fill="#F8F6FC", stroke=MID, radius=13, lw=1.4)
txt(679, 437, "D adds separate labels", size=13, color=PURPLE, bold=True)
rect(536, 455, 286, 82, fill="white", stroke=TEAL, radius=10, lw=1.5)
rect(546, 475, 52, 42, fill=LAVENDER, stroke="none", radius=8)
txt(572, 496, "Infer", size=12, color=INK, bold=True)
txt(711, 496, "What can you infer\nfrom the current\nstate?", size=14, color=INK)
rect(536, 547, 286, 64, fill="white", stroke=PURPLE, radius=10, lw=1.5)
rect(546, 558, 52, 42, fill=MID, stroke="none", radius=8)
txt(572, 579, "Plan", size=12, color=INK, bold=True)
txt(711, 579, "What to do given\nthe true inference?", size=15, color=INK)
line([(496, 437), (527, 437)], color=PURPLE, lw=2.3, head=True)
line([(679, 626), (679, 641)], color=PURPLE, lw=2.2, head=True)
rect(530, 648, 299, 68, fill=PURPLE_BG, stroke=PURPLE, radius=12, lw=1.8)
txt(679, 672, "GRPO training", size=19, color=PURPLE, bold=True)
txt(679, 698, "Qwen3-4B-Instruct-2507", size=14, color=INK)

# D. CalBench-style transfer: the focal model sees its own calendar and
# negotiates with partners whose private schedules are not disclosed.
rect(864, 247, 316, 490, fill=PANEL, stroke="#DDE6EE", radius=17)
panel_title(884, 278, "D", "Transfer", GREEN)
txt(1022, 311, "Coordinate a meeting\nwith private calendars", size=13, color=MUTED)
calendar_x = [883, 984, 1085]
for idx, x in enumerate(calendar_x):
    private = idx > 0
    rect(x, 339, 81, 220, fill="white", stroke=GREEN if idx == 0 else "#BCC9D2", radius=8, lw=1.5, dash=private)
    rect(x, 339, 81, 31, fill=GREEN_BG if idx == 0 else "#F0F3F6", stroke="none", radius=8)
    txt(x + 40, 354, "M" if idx == 0 else "AB"[idx - 1], size=13, color=GREEN if idx == 0 else INK, bold=True)
    for y in (390, 424, 458, 492, 526):
        line([(x + 9, y), (x + 72, y)], color="#DCE4E9", lw=1.0)
    if private:
        txt(x + 40, 450, "?", size=30, color="#A8B5C2", bold=True)
        txt(x + 40, 531, "private", size=12, color=MUTED)
    else:
        rect(x + 7, 402, 67, 15, fill="#DDEAF5", stroke="none", radius=3)
        rect(x + 7, 436, 67, 15, fill=MID, stroke="none", radius=3)
        rect(x + 7, 470, 67, 15, fill=LAVENDER_TINT, stroke=GREEN, radius=3, lw=1.2)
        txt(x + 40.5, 477.5, "free at 2", size=8.5, color=INK)
txt(1022, 611, "How can I coordinate with A and B\nmore efficiently?", size=12, color=INK)
line([(829, 682), (881, 682)], color=GREEN, lw=2.5, head=True)
rect(886, 650, 272, 65, fill=GREEN_BG, stroke=GREEN, radius=11, lw=1.6)
txt(1022, 675, "Transfer evaluation", size=17, color=GREEN, bold=True)
txt(1022, 698, "meeting coordination", size=13, color=INK)

for ext in ("pdf", "svg", "png"):
    fig.savefig(OUT / f"overview.{ext}", dpi=180, facecolor="white", bbox_inches=None, pad_inches=0)
plt.close(fig)

# Matplotlib leaves spaces at the ends of SVG path-data lines. Keep the
# generated asset clean so repository whitespace checks stay meaningful.
svg_path = OUT / "overview.svg"
svg_path.write_text("\n".join(line.rstrip() for line in svg_path.read_text().splitlines()) + "\n")

ET.indent(mxfile, space="  ")
(OUT / "overview.drawio").write_bytes(ET.tostring(mxfile, encoding="utf-8", xml_declaration=True))
