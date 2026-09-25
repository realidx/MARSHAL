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
WIDTH, HEIGHT = 1200, 760
INK = "#243446"
MUTED = "#607083"
LINE = "#C9D4DF"
PANEL = "#FAFBFD"
BLUE, BLUE_BG = "#386DA6", "#ECF3FC"
TEAL, TEAL_BG = "#287C79", "#EAF5F3"
PURPLE, PURPLE_BG = "#7756A4", "#F3EFFA"
ORANGE, ORANGE_BG = "#BA6A3D", "#FFF2E8"
GREEN, GREEN_BG = "#408063", "#E9F5EE"

fig = plt.figure(figsize=(12, 7.6), dpi=160)
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


def rect(x: float, y: float, w: float, h: float, *, fill: str = "white", stroke: str = LINE, radius: float = 12, lw: float = 1.5, dash: bool = False, zorder: float = 1) -> None:
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={radius}", facecolor=fill, edgecolor=stroke, linewidth=lw, linestyle="--" if dash else "-", zorder=zorder))
    arc = max(3, int(100 * radius / max(1, min(w, h))))
    vertex(x, y, w, h, f"rounded=1;arcSize={arc};whiteSpace=wrap;html=0;fillColor={fill};strokeColor={stroke};strokeWidth={lw};dashed={int(dash)};")


def disk(cx: float, cy: float, r: float, *, fill: str, stroke: str, lw: float = 1.5) -> None:
    ax.add_patch(Circle((cx, cy), r, facecolor=fill, edgecolor=stroke, linewidth=lw, zorder=4))
    vertex(cx - r, cy - r, 2 * r, 2 * r, f"ellipse;html=0;fillColor={fill};strokeColor={stroke};strokeWidth={lw};")


def txt(x: float, y: float, value: str, *, size: float = 16, color: str = INK, bold: bool = False, ha: str = "center", width: float | None = None, height: float | None = None) -> None:
    ax.text(x, y, value, fontsize=size, color=color, fontweight="bold" if bold else "normal", ha=ha, va="center", family="DejaVu Sans", linespacing=1.12, zorder=6)
    lines = value.split("\n")
    width = width or max(24, max(map(len, lines)) * size * 0.64)
    height = height or max(19, len(lines) * size * 1.35)
    left = x if ha == "left" else x - width if ha == "right" else x - width / 2
    vertex(left, y - height / 2, width, height, f"text;html=0;whiteSpace=wrap;overflow=visible;fillColor=none;strokeColor=none;fontFamily=Helvetica;fontSize={size};fontColor={color};fontStyle={1 if bold else 0};align={ha};verticalAlign=middle;", value)


def line(points: list[tuple[float, float]], *, color: str = LINE, lw: float = 1.8, head: bool = False, dash: bool = False) -> None:
    xs, ys = zip(*points)
    ax.plot(xs, ys, color=color, lw=lw, linestyle="--" if dash else "-", solid_capstyle="round", solid_joinstyle="round", zorder=2)
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
    txt(x, y, letter, size=20, color=color, bold=True, ha="left", width=25)
    txt(x + 30, y, title, size=19, bold=True, ha="left")


# A. Keep the user's three-agent scene visible across the interaction loop.
# A offers B a joint goal; M (the model) watches, infers A's preference, and
# proposes a collaboration of its own. Text labels annotate the scene only.
rect(20, 18, 1160, 211, fill=PANEL, stroke="#DDE6EE", radius=17, lw=1.5)
panel_title(40, 47, "A", "Interaction loop", TEAL)
txt(1138, 48, "A, B: partners     M: model", size=12, color=MUTED, ha="right")


def avatar(cx: float, cy: float, label: str, color: str, bg: str, *, pale: bool = False) -> None:
    stroke = "#AEBBC7" if pale else color
    fill = "#F1F4F7" if pale else bg
    disk(cx, cy, 14, fill=fill, stroke=stroke, lw=1.5)
    txt(cx, cy, label, size=12, color=stroke, bold=True)


def goal_chip(cx: float, cy: float, label: str, color: str, bg: str, width: float = 69) -> None:
    rect(cx - width / 2, cy - 15, width, 30, fill=bg, stroke=color, radius=8, lw=1.3, zorder=3)
    txt(cx, cy, label, size=11, color=color, bold=True)


scene_cards = [(40, "Observe", TEAL, TEAL_BG), (330, "Infer", PURPLE, PURPLE_BG),
               (620, "Plan", ORANGE, ORANGE_BG), (910, "Act", BLUE, BLUE_BG)]
for idx, (x, title, color, bg) in enumerate(scene_cards, 1):
    rect(x, 72, 250, 115, fill="white", stroke="#CBD7E1", radius=13)
    disk(x + 27, 94, 12, fill=bg, stroke=color, lw=1.3)
    txt(x + 27, 94, str(idx), size=13, color=color, bold=True)
    txt(x + 48, 94, title, size=17, color=color, bold=True, ha="left")

# 1. A proposes goal g to B; the model observes that move.
x = 40
line([(x + 59, 150), (x + 190, 150)], color=TEAL, lw=1.6, head=True)
line([(x + 125, 146), (x + 125, 155)], color=TEAL, lw=1.5, dash=True)
goal_chip(x + 125, 130, "goal g", TEAL, TEAL_BG, width=66)
avatar(x + 44, 150, "A", ORANGE, ORANGE_BG)
avatar(x + 205, 150, "B", GREEN, GREEN_BG)
avatar(x + 125, 169, "M", BLUE, BLUE_BG)

# 2. The same observed proposal becomes evidence about A's preference.
x = 330
line([(x + 59, 150), (x + 78, 138)], color=PURPLE, lw=1.3, dash=True)
line([(x + 125, 146), (x + 125, 155)], color=PURPLE, lw=1.3, dash=True)
goal_chip(x + 125, 130, "A likes g?", PURPLE, PURPLE_BG, width=94)
avatar(x + 44, 150, "A", ORANGE, ORANGE_BG)
avatar(x + 205, 150, "B", GREEN, GREEN_BG, pale=True)
avatar(x + 125, 169, "M", BLUE, BLUE_BG)

# 3. The model compares the benefit to A and to itself.
x = 620
line([(x + 59, 150), (x + 76, 138)], color=ORANGE, lw=1.5)
line([(x + 125, 146), (x + 125, 155)], color=ORANGE, lw=1.5)
goal_chip(x + 125, 130, "A + M gain", ORANGE, ORANGE_BG, width=98)
avatar(x + 44, 150, "A", ORANGE, ORANGE_BG)
avatar(x + 205, 150, "B", GREEN, GREEN_BG, pale=True)
avatar(x + 125, 169, "M", BLUE, BLUE_BG)

# 4. M acts on that plan and invites A; B remains the other participant.
x = 910
line([(x + 111, 163), (x + 59, 155)], color=BLUE, lw=1.7, head=True)
goal_chip(x + 130, 130, "g together?", BLUE, BLUE_BG, width=99)
avatar(x + 44, 150, "A", ORANGE, ORANGE_BG)
avatar(x + 205, 150, "B", GREEN, GREEN_BG, pale=True)
avatar(x + 125, 169, "M", BLUE, BLUE_BG)

for x in (290, 580, 870):
    line([(x + 3, 132), (x + 35, 132)], color=MUTED, lw=2.0, head=True)
line([(1123, 187), (1123, 209), (76, 209), (76, 188)], color=TEAL, lw=1.7, head=True)

# B. The full game tree, with three different contiguous slices on its paths.
rect(20, 247, 476, 490, fill=PANEL, stroke="#DDE6EE", radius=17)
panel_title(40, 278, "B", "Game tree and slices", PURPLE)
txt(250, 307, "SP: root to terminal outcome", size=14, color=BLUE)
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
    ("a", "aa"): PURPLE, ("aa", "aaa"): PURPLE,
    ("ab", "abb"): TEAL,
    ("b", "bb"): ORANGE, ("bb", "bbb"): ORANGE,
}
for src, dst in edges:
    color = slices.get((src, dst), "#BCC8D4")
    line([node[src], node[dst]], color=color, lw=4.0 if (src, dst) in slices else 1.8)
selected_nodes = {"a": PURPLE, "aa": PURPLE, "aaa": PURPLE, "ab": TEAL, "abb": TEAL, "b": ORANGE, "bb": ORANGE, "bbb": ORANGE}
for name, (x, y) in node.items():
    accent = selected_nodes.get(name)
    disk(x, y, 7 if name not in {"aaa", "aab", "aba", "abb", "baa", "bab", "bba", "bbb"} else 5.3, fill=accent or "white", stroke=accent or "#9EAFBE", lw=1.5)
for x, y, label, color, bg in [(50, 605, "slice 1", PURPLE, PURPLE_BG), (201, 605, "slice 2", TEAL, TEAL_BG), (414, 605, "slice 3", ORANGE, ORANGE_BG)]:
    rect(x - 31, y - 15, 84, 30, fill=bg, stroke=color, radius=9, lw=1.3)
    txt(x + 11, y, label, size=13, color=color, bold=True)
txt(258, 675, "Colored paths mark consecutive decisions", size=13, color=MUTED)
txt(258, 700, "A slice may start below the root", size=12, color=MUTED)

# C. Three supervision prompts derived from each chosen slice.
rect(510, 247, 339, 490, fill=PANEL, stroke="#DDE6EE", radius=17)
panel_title(530, 278, "C", "Supervision", PURPLE)
txt(679, 304, "Generate oracle labels", size=14, color=MUTED)
question_cards = [
    (328, "Q1", "What to do given\nthe history?", BLUE, BLUE_BG),
    (421, "Q2", "What can you infer\ngiven the history?", TEAL, TEAL_BG),
    (514, "Q3", "What to do given\nthe true inference?", PURPLE, PURPLE_BG),
]
for y, key, question, color, bg in question_cards:
    rect(529, y, 300, 80, fill="white", stroke=color, radius=11, lw=1.6)
    rect(541, y + 15, 49, 49, fill=bg, stroke="none", radius=10)
    txt(566, y + 39, key, size=16, color=color, bold=True)
    txt(706, y + 39, question, size=16, color=INK)
line([(496, 481), (527, 481)], color=PURPLE, lw=2.3, head=True)
line([(679, 594), (679, 641)], color=PURPLE, lw=2.2, head=True)
rect(530, 648, 299, 68, fill=PURPLE_BG, stroke=PURPLE, radius=12, lw=1.8)
txt(679, 672, "GRPO training", size=19, color=PURPLE, bold=True)
txt(679, 698, "Qwen3-4B-Instruct-2507", size=14, color=INK)

# D. CalBench-style transfer: the focal model sees its own calendar and
# negotiates with partners whose private schedules are not disclosed.
rect(864, 247, 316, 490, fill=PANEL, stroke="#DDE6EE", radius=17)
panel_title(884, 278, "D", "Transfer", GREEN)
txt(1022, 309, "CalBench: private calendars", size=14, color=MUTED)
calendar_x = [883, 984, 1085]
for idx, x in enumerate(calendar_x):
    private = idx > 0
    rect(x, 339, 81, 220, fill="white", stroke=GREEN if idx == 0 else "#BCC9D2", radius=8, lw=1.5, dash=private)
    rect(x, 339, 81, 31, fill=GREEN_BG if idx == 0 else "#F0F3F6", stroke="none", radius=8)
    txt(x + 40, 354, "Self" if idx == 0 else "AB"[idx - 1], size=13, color=GREEN if idx == 0 else INK, bold=True)
    for y in (390, 424, 458, 492, 526):
        line([(x + 9, y), (x + 72, y)], color="#DCE4E9", lw=1.0)
    if private:
        txt(x + 40, 450, "?", size=30, color="#A8B5C2", bold=True)
        txt(x + 40, 531, "private", size=12, color=MUTED)
    else:
        rect(x + 12, 402, 57, 15, fill="#DDEAF5", stroke="none", radius=3)
        rect(x + 12, 436, 57, 15, fill="#FFE8DB", stroke="none", radius=3)
        rect(x + 12, 470, 57, 15, fill=GREEN_BG, stroke=GREEN, radius=3, lw=1.2)
        txt(x + 40, 531, "free at 2", size=11, color=GREEN)
line([(1039, 585), (1117, 585)], color=GREEN, lw=2.0, head=True)
rect(915, 568, 122, 35, fill="white", stroke=GREEN, radius=9, lw=1.4)
txt(976, 585, "2 pm?", size=14, color=GREEN, bold=True)
txt(1022, 622, "Propose, then adapt to replies", size=13, color=MUTED)
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
