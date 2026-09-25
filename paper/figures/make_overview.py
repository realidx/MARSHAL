"""Generate the editable and publication versions of the paper overview figure.

The coordinates below are shared by the PDF/SVG/PNG rendering and the native
draw.io file. Run from any directory with ``python paper/figures/make_overview.py``.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Polygon


OUT = Path(__file__).resolve().parent
W, H = 1200, 560
INK = "#243446"
MUTED = "#586879"
LINE = "#CBD4DE"
PANEL = "#F8FAFC"
BLUE = "#376EAA"
BLUE_BG = "#EAF3FC"
PURPLE = "#7655A5"
PURPLE_BG = "#F4EFFA"
TEAL = "#257D79"
TEAL_BG = "#EBF6F4"
ORANGE = "#BF7040"
ORANGE_BG = "#FFF3E9"
GREEN = "#3D8065"
GREEN_BG = "#E9F5EE"

fig = plt.figure(figsize=(12, 5.6), dpi=160)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.set_aspect("equal")
ax.axis("off")
fig.patch.set_facecolor("white")
ax.set_facecolor("white")

graph = ET.Element("mxfile", {"host": "app.diagrams.net", "modified": "2026-09-26T00:00:00.000Z", "agent": "Codex", "version": "24.7.17", "type": "device"})
diagram = ET.SubElement(graph, "diagram", {"id": "overview", "name": "Overview"})
model = ET.SubElement(diagram, "mxGraphModel", {"dx": "1200", "dy": "560", "grid": "0", "page": "1", "pageScale": "1", "pageWidth": str(W), "pageHeight": str(H), "math": "0", "shadow": "0"})
root = ET.SubElement(model, "root")
ET.SubElement(root, "mxCell", {"id": "0"})
ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
counter = 1


def new_id() -> str:
    global counter
    counter += 1
    return str(counter)


def cell(style: str, x: float, y: float, width: float, height: float, value: str = "") -> None:
    c = ET.SubElement(root, "mxCell", {"id": new_id(), "value": value, "style": style, "vertex": "1", "parent": "1"})
    ET.SubElement(c, "mxGeometry", {"x": str(x), "y": str(H - y - height), "width": str(width), "height": str(height), "as": "geometry"})


def box(x: float, y: float, width: float, height: float, *, fill: str = "white", stroke: str = LINE, radius: float = 14, lw: float = 1.4) -> None:
    ax.add_patch(FancyBboxPatch((x, y), width, height, boxstyle=f"round,pad=0,rounding_size={radius}", facecolor=fill, edgecolor=stroke, linewidth=lw, zorder=1))
    cell(f"rounded=1;arcSize={int(100 * radius / max(1, min(width, height)))};whiteSpace=wrap;html=0;fillColor={fill};strokeColor={stroke};strokeWidth={lw};", x, y, width, height)


def circle(x: float, y: float, radius: float, *, fill: str, stroke: str, lw: float = 1.5) -> None:
    ax.add_patch(Circle((x, y), radius, facecolor=fill, edgecolor=stroke, linewidth=lw, zorder=3))
    cell(f"ellipse;whiteSpace=wrap;html=0;fillColor={fill};strokeColor={stroke};strokeWidth={lw};", x - radius, y - radius, 2 * radius, 2 * radius)


def label(x: float, y: float, value: str, *, size: float = 18, color: str = INK, weight: str = "normal", ha: str = "center", va: str = "center", width: float | None = None, height: float | None = None) -> None:
    ax.text(x, y, value, fontsize=size, color=color, fontweight=weight, ha=ha, va=va, family="DejaVu Sans", linespacing=1.1, zorder=5)
    lines = value.split("\n")
    width = width or max(30, max(map(len, lines)) * size * 0.62)
    height = height or len(lines) * size * 1.3
    align = {"left": "left", "right": "right", "center": "center"}[ha]
    cell(f"text;html=0;whiteSpace=wrap;overflow=visible;fillColor=none;strokeColor=none;fontFamily=Helvetica;fontSize={size};fontColor={color};fontStyle={1 if weight == 'bold' else 0};align={align};verticalAlign=middle;", x - (0 if ha == "left" else width if ha == "right" else width / 2), y - height / 2, width, height, value)


def arrow(points: list[tuple[float, float]], *, color: str = INK, lw: float = 2, dashed: bool = False, head: bool = True) -> None:
    xs, ys = zip(*points)
    ax.plot(xs, ys, color=color, linewidth=lw, linestyle="--" if dashed else "-", solid_capstyle="round", zorder=2)
    if head:
        ax.add_patch(FancyArrowPatch(points[-2], points[-1], arrowstyle="-|>", mutation_scale=13, color=color, linewidth=lw, zorder=4))
    c = ET.SubElement(root, "mxCell", {"id": new_id(), "style": f"edgeStyle=none;rounded=0;html=0;strokeColor={color};strokeWidth={lw};dashed={1 if dashed else 0};endArrow={'block' if head else 'none'};endFill=1;", "edge": "1", "parent": "1"})
    g = ET.SubElement(c, "mxGeometry", {"relative": "1", "as": "geometry"})
    ET.SubElement(g, "mxPoint", {"x": str(points[0][0]), "y": str(H - points[0][1]), "as": "sourcePoint"})
    ET.SubElement(g, "mxPoint", {"x": str(points[-1][0]), "y": str(H - points[-1][1]), "as": "targetPoint"})
    if len(points) > 2:
        ar = ET.SubElement(g, "Array", {"as": "points"})
        for px, py in points[1:-1]:
            ET.SubElement(ar, "mxPoint", {"x": str(px), "y": str(H - py)})


def tree_edge(a: tuple[float, float], b: tuple[float, float], *, active: bool = False) -> None:
    arrow([a, b], color=PURPLE if active else "#AAB7C5", lw=3.3 if active else 1.8, head=False)


# Panel frames and headings.
box(18, 45, 300, 490, fill=PANEL, stroke="#E2E8EE", radius=17)
box(333, 45, 534, 490, fill=PANEL, stroke="#E2E8EE", radius=17)
box(882, 45, 300, 490, fill=PANEL, stroke="#E2E8EE", radius=17)
arrow([(306, 279), (345, 279)], color=MUTED, lw=1.9)
label(43, 509, "A", size=19, color=TEAL, weight="bold", ha="left")
label(74, 509, "Interaction loop", size=19, weight="bold", ha="left")
label(357, 509, "B", size=19, color=PURPLE, weight="bold", ha="left")
label(387, 509, "Game sampling and training", size=19, weight="bold", ha="left")
label(906, 509, "C", size=19, color=GREEN, weight="bold", ha="left")
label(936, 509, "Transfer", size=19, weight="bold", ha="left")

# A: abstract three-agent negotiation, then the closed observation/action loop.
for x, name, color, bg in [(89, "A", TEAL, TEAL_BG), (169, "B", ORANGE, ORANGE_BG), (249, "C", BLUE, BLUE_BG)]:
    circle(x, 450, 20, fill=bg, stroke=color)
    label(x, 450, name, size=18, color=color, weight="bold")
arrow([(95, 427), (123, 412)], color=TEAL, lw=1.6)
arrow([(169, 427), (169, 414)], color=ORANGE, lw=1.6)
arrow([(243, 427), (215, 412)], color=BLUE, lw=1.6)
box(75, 375, 188, 39, fill="white", stroke=LINE, radius=11)
label(169, 394, "negotiation", size=16)

box(84, 289, 188, 45, fill=TEAL_BG, stroke=TEAL, radius=12)
label(178, 312, "Observe", size=17, color=TEAL, weight="bold")
box(84, 207, 188, 45, fill=PURPLE_BG, stroke=PURPLE, radius=12)
label(178, 230, "Infer preferences", size=14, color=PURPLE, weight="bold")
box(84, 125, 188, 45, fill=ORANGE_BG, stroke=ORANGE, radius=12)
label(178, 148, "Act", size=17, color=ORANGE, weight="bold")
arrow([(178, 375), (178, 336)], color=MUTED, lw=1.8)
arrow([(178, 287), (178, 255)], color=MUTED, lw=1.8)
arrow([(178, 205), (178, 173)], color=MUTED, lw=1.8)
arrow([(84, 146), (53, 146), (53, 312), (81, 312)], color=TEAL, lw=2.1)

# B: a shallow extensive-form tree. The purple overlay begins below the root
# and encloses two consecutive decisions on one realized path.
root_node = (575, 439)
left1, right1 = (456, 384), (690, 384)
left2a, left2b = (397, 328), (510, 328)
right2a, right2b = (630, 328), (748, 328)
leaf_a, leaf_b, leaf_c, leaf_d = (590, 274), (668, 274), (716, 274), (780, 274)
for a, b, selected in [
    (root_node, left1, False), (root_node, right1, False),
    (left1, left2a, False), (left1, left2b, False),
    (right1, right2a, True), (right1, right2b, False),
    (right2a, leaf_a, False), (right2a, leaf_b, True),
    (right2b, leaf_c, False), (right2b, leaf_d, False),
]:
    tree_edge(a, b, active=selected)

box(605, 257, 86, 150, fill="none", stroke=PURPLE, radius=15, lw=2.4)
for node in [root_node, left1, right1, left2a, left2b, right2a, right2b, leaf_a, leaf_b, leaf_c, leaf_d]:
    active = node in [right1, right2a, leaf_b]
    circle(*node, 8 if node not in [leaf_a, leaf_b, leaf_c, leaf_d] else 6, fill=PURPLE if active else "white", stroke=PURPLE if active else "#9BABB9", lw=1.7)
label(751, 409, "slice", size=15, color=PURPLE, weight="bold")
label(754, 291, "1+ turns", size=13, color=PURPLE)
arrow([(400, 459), (565, 442)], color=BLUE, lw=2.3)
label(392, 477, "SP starts at root", size=15, color=BLUE, ha="left")

# The two routes remain separate training arms. Both initialize from the same
# checkpoint; the shared-base note is deliberately not a merge node.
box(362, 157, 205, 62, fill=BLUE_BG, stroke=BLUE, radius=11)
label(465, 190, "SP", size=17, color=BLUE, weight="bold")
label(465, 171, "full games", size=14, color=MUTED)
box(615, 157, 225, 62, fill=PURPLE_BG, stroke=PURPLE, radius=11)
label(727, 190, "O / D", size=17, color=PURPLE, weight="bold")
label(727, 171, "oracle-labeled slices", size=14, color=MUTED)
arrow([(424, 312), (402, 255), (429, 222)], color=BLUE, lw=2)
arrow([(667, 253), (717, 222)], color=PURPLE, lw=2)
box(416, 83, 376, 40, fill="white", stroke="#BAC6D2", radius=10)
label(604, 103, "Same 4B base; separate training", size=14, color=INK)
arrow([(465, 156), (465, 139), (846, 139)], color=GREEN, lw=1.9, head=False)
arrow([(727, 156), (727, 139)], color=GREEN, lw=1.9, head=False)
arrow([(846, 139), (915, 139)], color=GREEN, lw=2.6)

# C: a stylized CalBench transfer task with three private calendars and one
# proposed common meeting slot. It denotes evaluation, not a success result.
label(1031, 466, "Calendar coordination", size=15, color=GREEN, weight="bold")
label(1031, 439, "private schedules", size=13, color=MUTED)
cal_x = [913, 1006, 1099]
for idx, x in enumerate(cal_x):
    box(x, 261, 68, 147, fill="white", stroke="#AFC0CA", radius=8)
    box(x, 381, 68, 27, fill=TEAL_BG if idx == 0 else BLUE_BG if idx == 1 else ORANGE_BG, stroke="none", radius=8)
    label(x + 34, 394, "ABC"[idx], size=13, color=INK, weight="bold")
    for y in (356, 330, 304, 278):
        arrow([(x + 9, y), (x + 59, y)], color="#DAE3E9", lw=1, head=False)
    for y, fill in ([(338, BLUE_BG), (286, ORANGE_BG)] if idx == 0 else [(312, PURPLE_BG)] if idx == 1 else [(338, ORANGE_BG), (312, BLUE_BG)]):
        box(x + 12, y, 44, 13, fill=fill, stroke="none", radius=3)
    box(x + 12, 358, 44, 12, fill=GREEN_BG, stroke=GREEN, radius=3)
label(1031, 232, "Coordinate a meeting", size=14, color=INK)
box(918, 123, 226, 61, fill=GREEN_BG, stroke=GREEN, radius=12)
label(1031, 158, "CalBench", size=17, color=GREEN, weight="bold")
label(1031, 137, "held-out task", size=13, color=MUTED)

for extension in ("pdf", "svg", "png"):
    fig.savefig(OUT / f"overview.{extension}", dpi=180, facecolor="white", bbox_inches=None, pad_inches=0)
plt.close(fig)

ET.indent(graph, space="  ")
(OUT / "overview.drawio").write_bytes(ET.tostring(graph, encoding="utf-8", xml_declaration=True))
