"""Draw an illustrative BENAC-I game in editable and print formats.

This is an adapted legal trajectory, not a recorded model or oracle rollout.
Each goal uses separate action coordinates: A and C have one bridge action
and one supply action; B has one bridge action. The preference world and
action path were chosen to explain the mechanics.
The public proposer schedule is B, A, C, B, A, C, B. Actions are:
B offers bridge actions (B=1,C=1), C rejects; A investigates C's supply
preference; C passes; B investigates A's bridge preference; A offers supply
actions (A=1,C=1), C accepts;
C passes; B offers bridge actions (B=1,A=1), A accepts.
The native offer/state rules validate the sequence.
Run with an environment containing matplotlib:
    python paper/figures/make_game_flow.py
"""

from pathlib import Path
from xml.etree import ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch


OUT = Path(__file__).resolve().parent
W, H = 1500, 615
INK = "#3F3540"
MUTED = "#716770"
LINE = "#D9CCD1"
ROSE = "#E8C1CC"  # A
APRICOT = "#FFD7A8"  # B
CORAL = "#F3A683"  # C
ROSE_DARK = "#9B6273"
APRICOT_DARK = "#986B3F"
CORAL_DARK = "#9A533E"
PANEL_FILLS = ("#FFF8FA", "#FFFAF3", "#FFF7F2")

fig = plt.figure(figsize=(15, 6.15), dpi=150)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, W)
ax.set_ylim(H, 0)
ax.set_aspect("equal")
ax.axis("off")
fig.patch.set_facecolor("white")

mxfile = ET.Element("mxfile", {"host": "app.diagrams.net", "agent": "MARSHAL paper", "type": "device"})
diagram = ET.SubElement(mxfile, "diagram", {"id": "game-flow", "name": "Three-player game flow"})
model = ET.SubElement(diagram, "mxGraphModel", {"dx": str(W), "dy": str(H), "grid": "0", "page": "1", "pageScale": "1", "pageWidth": str(W), "pageHeight": str(H), "math": "0", "shadow": "0"})
root = ET.SubElement(model, "root")
ET.SubElement(root, "mxCell", {"id": "0"})
ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
next_id = 2


def vertex(x, y, w, h, style, value=""):
    global next_id
    c = ET.SubElement(root, "mxCell", {"id": str(next_id), "parent": "1", "vertex": "1", "style": style, "value": value})
    next_id += 1
    ET.SubElement(c, "mxGeometry", {"x": str(x), "y": str(y), "width": str(w), "height": str(h), "as": "geometry"})


def rect(x, y, w, h, fill="white", stroke=LINE, radius=12, lw=1.4, dashed=False, zorder=1):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={radius}", facecolor=fill, edgecolor=stroke, linewidth=lw, linestyle="--" if dashed else "-", zorder=zorder))
    vertex(x, y, w, h, f"rounded=1;arcSize={max(5, int(100*radius/min(w,h)))};whiteSpace=wrap;html=0;fillColor={fill};strokeColor={stroke};strokeWidth={lw};dashed={int(dashed)};")


def disk(cx, cy, r, fill, stroke="none", lw=1.0):
    ax.add_patch(Circle((cx, cy), r, facecolor=fill, edgecolor=stroke, linewidth=lw, zorder=3))
    vertex(cx-r, cy-r, 2*r, 2*r, f"ellipse;html=0;fillColor={fill};strokeColor={stroke};strokeWidth={lw};")


def txt(x, y, value, size=15, color=INK, bold=False, ha="center", width=None, height=None):
    ax.text(x, y, value, fontsize=size, color=color, fontweight="bold" if bold else "normal", ha=ha, va="center", family="DejaVu Sans", linespacing=1.12, zorder=6)
    lines = value.split("\n")
    width = width or max(30, max(map(len, lines))*size*0.62)
    height = height or max(20, len(lines)*size*1.3)
    left = x if ha == "left" else x-width if ha == "right" else x-width/2
    vertex(left, y-height/2, width, height, f"text;html=0;whiteSpace=wrap;overflow=visible;fillColor=none;strokeColor=none;fontFamily=Helvetica;fontSize={size};fontColor={color};fontStyle={1 if bold else 0};align={ha};verticalAlign=middle;", value)


def arrow(points, color=INK, lw=2.2, dashed=False, head=True):
    xs, ys = zip(*points)
    ax.plot(xs, ys, color=color, linewidth=lw, linestyle="--" if dashed else "-", solid_capstyle="round", zorder=2)
    if head:
        ax.add_patch(FancyArrowPatch(points[-2], points[-1], arrowstyle="-|>", mutation_scale=15, color=color, linewidth=lw, zorder=4))
    global next_id
    edge = ET.SubElement(root, "mxCell", {"id": str(next_id), "parent": "1", "edge": "1", "style": f"edgeStyle=none;html=0;strokeColor={color};strokeWidth={lw};dashed={int(dashed)};endArrow={'block' if head else 'none'};endFill=1;"})
    next_id += 1
    geo = ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
    ET.SubElement(geo, "mxPoint", {"x": str(points[0][0]), "y": str(points[0][1]), "as": "sourcePoint"})
    ET.SubElement(geo, "mxPoint", {"x": str(points[-1][0]), "y": str(points[-1][1]), "as": "targetPoint"})
    if len(points) > 2:
        bends = ET.SubElement(geo, "Array", {"as": "points"})
        for x, y in points[1:-1]:
            ET.SubElement(bends, "mxPoint", {"x": str(x), "y": str(y)})


def badge(x, y, text, fill, border, text_color=INK, width=115):
    rect(x-width/2, y-17, width, 34, fill=fill, stroke=border, radius=17, lw=1.2)
    txt(x, y, text, size=13, color=text_color, bold=True)


def player(x, y, letter, fill, dark, private=None):
    disk(x, y, 35, "white", LINE, 1.2)
    disk(x, y-9, 10, fill, dark, 1.2)
    rect(x-17, y+4, 34, 18, fill=fill, stroke=dark, radius=9, lw=1.2, zorder=4)
    txt(x, y+47, f"Player {letter}", size=15, color=dark, bold=True)
    if private:
        rect(x-68, y+65, 136, 51, fill="white", stroke=dark, radius=8, lw=1.0)
        txt(x, y+90, private, size=9.4, color=dark, bold=True, height=39)


def panel(x, number, title, subtitle, fill, accent):
    rect(x, 20, 470, 575, fill=fill, stroke=LINE, radius=20, lw=1.5)
    disk(x+38, 59, 19, accent, "white", 1.3)
    txt(x+38, 59, str(number), size=16, color=INK, bold=True)
    txt(x+69, 56, title, size=20, color=INK, bold=True, ha="left")
    if subtitle:
        txt(x+31, 92, subtitle, size=13, color=MUTED, ha="left")


def goal_status(x, bridge_committed=(), supplies_committed=()):
    rect(x+28, 428, 414, 130, fill="white", stroke=LINE, radius=12)
    txt(x+45, 449, "Goal contributions", size=12, color=MUTED, bold=True, ha="left")
    txt(x+424, 449, "filled = committed", size=10, color=MUTED, ha="right")
    for y, name, required, committed in (
        (483, "Repair bridge", "ABC", set(bridge_committed)),
        (528, "Deliver supplies", "AC", set(supplies_committed)),
    ):
        txt(x+45, y, name, size=14, color=INK, bold=True, ha="left")
        for j, letter in enumerate(required):
            fill = {"A": ROSE, "B": APRICOT, "C": CORAL}[letter] if letter in committed else "white"
            rect(x+255+36*j, y-14, 29, 28, fill=fill, stroke=LINE, radius=7, lw=1.2)
            txt(x+269.5+36*j, y, letter, size=12, color=INK, bold=True)
        txt(x+424, y, f"{len(committed)}/{len(required)}", size=13, color=INK,
            bold=len(committed) == len(required), ha="right")


# The same three players remain visible in every scene. Preference cards in
# scene 1 depict the illustrative world for the reader; each card is private.
X1, X2, X3 = 20, 515, 1010
panel(X1, 1, "Offer and investigate", "C's rejection prompts A to probe supplies", PANEL_FILLS[0], ROSE)
txt(X1+31, 112, "Round robin: B → A → C, repeated", size=11, color=MUTED, ha="left")
player(X1+86, 157, "A", ROSE, ROSE_DARK, "Bridge: want\nSupplies: want")
player(X1+235, 157, "B", APRICOT, APRICOT_DARK, "Bridge: want\nSupplies: neutral")
player(X1+384, 157, "C", CORAL, CORAL_DARK, "Bridge: avoid\nSupplies: want")
txt(X1+235, 292, "B offers: B and C take bridge actions", size=15, bold=True)
arrow([(X1+252, 315), (X1+367, 315)], APRICOT_DARK, 2.5)
badge(X1+375, 337, "C rejects", "white", CORAL_DARK, CORAL_DARK, 126)
txt(X1+235, 369, "A investigates C's supply preference", size=14, bold=True)
arrow([(X1+102, 393), (X1+367, 393)], ROSE_DARK, 2.0, dashed=True)
rect(X1+269, 402, 180, 22, fill="white", stroke=CORAL_DARK, radius=8, lw=1.1, dashed=True)
txt(X1+359, 413, "Only A learns: want", size=11, color=CORAL_DARK, bold=True)
goal_status(X1)

panel(X2, 2, "Investigate and revise", "B learns A wants the bridge; A secures supplies", PANEL_FILLS[1], APRICOT)
player(X2+86, 157, "A", ROSE, ROSE_DARK)
player(X2+235, 157, "B", APRICOT, APRICOT_DARK)
player(X2+384, 157, "C", CORAL, CORAL_DARK)
badge(X2+384, 233, "C passes", "white", CORAL_DARK, CORAL_DARK, 118)
txt(X2+235, 269, "B investigates A's bridge preference", size=14, bold=True)
arrow([(X2+219, 292), (X2+102, 292)], APRICOT_DARK, 2.0, dashed=True)
rect(X2+35, 306, 180, 25, fill="white", stroke=ROSE_DARK, radius=8, lw=1.1, dashed=True)
txt(X2+125, 318.5, "Only B learns: want", size=11, color=ROSE_DARK, bold=True)
txt(X2+235, 359, "A offers: A and C deliver supplies", size=15, bold=True)
arrow([(X2+102, 382), (X2+367, 382)], ROSE_DARK, 2.5)
badge(X2+376, 407, "C accepts", "white", CORAL_DARK, CORAL_DARK, 126)
goal_status(X2, supplies_committed=("A", "C"))

panel(X3, 3, "Final bridge offer", "B gains A's support; bridge reaches 2/3", PANEL_FILLS[2], CORAL)
player(X3+86, 157, "A", ROSE, ROSE_DARK)
player(X3+235, 157, "B", APRICOT, APRICOT_DARK)
player(X3+384, 157, "C", CORAL, CORAL_DARK)
badge(X3+384, 255, "C passes", "white", CORAL_DARK, CORAL_DARK, 118)
txt(X3+235, 310, "B offers: B and A take bridge actions", size=15, bold=True)
arrow([(X3+220, 347), (X3+102, 347)], APRICOT_DARK, 2.5)
badge(X3+96, 388, "A accepts", "white", ROSE_DARK, ROSE_DARK, 126)
goal_status(X3, bridge_committed=("A", "B"), supplies_committed=("A", "C"))

# The horizontal connectors carry the chronology between the three panels.
arrow([(490, 496), (510, 496)], INK, 1.7)
arrow([(985, 496), (1005, 496)], INK, 1.7)

ET.indent(mxfile, space="  ")
ET.ElementTree(mxfile).write(OUT / "game_flow.drawio", encoding="utf-8", xml_declaration=True)
for ext in ("svg", "pdf", "png"):
    fig.savefig(OUT / f"game_flow.{ext}", facecolor="white", dpi=200)
plt.close(fig)
