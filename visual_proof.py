"""Draw the structural problems found in the extractor's JSON on top of the PDF page.

Problems are detected from the current extractor output, not hard-coded, so
the same script shows the state before a fix and after it:

    .\\.venv\\Scripts\\python.exe visual_proof.py before
    .\\.venv\\Scripts\\python.exe visual_proof.py after
"""
from pathlib import Path
import json
import sys

import pdfplumber
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from extractor.engine import PARSER_VERSION, extract_pdf

RESOLUTION = 150
SCALE = RESOLUTION / 72
RED, BLUE, ORANGE, GREEN, GREY, MAGENTA = (220, 30, 30), (30, 90, 220), (240, 140, 0), (20, 150, 60), (150, 150, 150), (200, 0, 200)
FONT = ImageFont.truetype("arial.ttf", 17)
BOLD = ImageFont.truetype("arialbd.ttf", 19)

# (pdf, page, issue title, what the region shows). Regions are found from the JSON.
CASES = [
    ("Table 06_Ver.01.pdf", 5, "table06_p5_overlapping_cells",
     "Table 06 page 5: one printed '-' stored in two overlapping cells"),
    ("Table 06_Ver.01.pdf", 9, "table06_p9_overlapping_cells",
     "Table 06 page 9: one printed 'Optional' stored in two overlapping cells"),
    ("Table 06_Ver.01.pdf", 8, "table06_p8_text_without_cell",
     "Table 06 page 8: printed 'E 22.4' has no cell in the JSON"),
    ("Table 06_Ver.01.pdf", 9, "table06_p9_text_without_cell",
     "Table 06 page 9: printed 'E 31.6' and its label have no cell in the JSON"),
    ("Table 11_Ver.01.pdf", 1, "table11_p1_span_outside_grid",
     "Table 11 page 1: merged cell spans a column the table does not declare"),
    ("Table 03_Ver.01.pdf", 7, "table03_p7_nested_table",
     "Table 03 page 7: inner table text also stored in the outer cell"),
    ("Table 03_Ver.01.pdf", 16, "table03_p16_nested_table",
     "Table 03 page 16: inner table text also stored in the outer cell"),
]


def inside(box, x, y):
    return box[0] - .01 <= x < box[2] + .01 and box[1] - .01 <= y < box[3] + .01


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def char_centre(char):
    return (char["x0"] + char["x1"]) / 2, (char["top"] + char["bottom"]) / 2


def find_problems(page_json, chars):
    """Each problem: kind, boxes to highlight (with colour), and the JSON evidence."""
    problems = []
    tables = page_json["tables"]
    # 1. One printed character inside two cells of the same table.
    for table in tables:
        shared = {}
        for char in chars:
            if not char["text"].strip():
                continue
            owners = [c for c in table["cells"] if inside(c["bbox"], *char_centre(char))]
            if len(owners) > 1:
                key = tuple(tuple(c["bbox"]) for c in owners)
                shared.setdefault(key, (owners, []))[1].append(char)
        for owners, shared_chars in shared.values():
            problems.append({"kind": "overlapping_cells", "table": table["id"],
                             "boxes": [(c["bbox"], RED if i == 0 else BLUE) for i, c in enumerate(owners)]
                             + [(c_bbox(ch), ORANGE) for ch in shared_chars],
                             "evidence": [cell_json(table, c) for c in owners]})
    # 2. Printed text inside a table's outline but in no cell.
    table_boxes = [t["bbox"] for t in tables]
    all_cells = [c for t in tables for c in t["cells"]]
    loose = [ch for ch in chars if ch["text"].strip()
             and any(inside(b, *char_centre(ch)) for b in table_boxes)
             and not any(inside(c["bbox"], *char_centre(ch)) for c in all_cells)]
    for line in group_lines(loose):
        table = next(t for t in tables if inside(t["bbox"], *char_centre(line[0])))
        problems.append({"kind": "text_without_cell", "table": table["id"],
                         "text": "".join(ch["text"] for ch in line),
                         "boxes": [(c_bbox(ch), ORANGE) for ch in line],
                         "evidence": text_cell_json(table, line)})
    # 3. A cell span running past the table's declared grid.
    for table in tables:
        for cell in table["cells"]:
            if (cell["column"] + cell["column_span"] > table["column_count"]
                    or cell["row"] + cell["row_span"] > table["row_count"]):
                problems.append({"kind": "span_outside_grid", "table": table["id"],
                                 "boxes": [(cell["bbox"], RED)],
                                 "columns": column_edges(table),
                                 "evidence": {"table": {k: table[k] for k in ("id", "row_count", "column_count")},
                                              "cell": cell}})
    # 4. A table drawn inside another table's cell, with its text stored twice.
    for outer in tables:
        for inner in tables:
            if inner is outer or not all(outer["bbox"][i] <= inner["bbox"][i] + .5 for i in (0, 1)) \
                    or not all(inner["bbox"][i] <= outer["bbox"][i] + .5 for i in (2, 3)):
                continue
            hosts = [c for c in outer["cells"] if overlaps(c["bbox"], inner["bbox"])]
            squash = lambda text: "".join((text or "").split())
            repeated = [c["text"] for c in inner["cells"] if squash(c["text"])
                        and any(squash(c["text"]) in squash(h["text"]) for h in hosts)]
            if repeated or not inner.get("parent"):
                problems.append({"kind": "nested_table_duplicate_text", "table": outer["id"],
                                 "boxes": [(c["bbox"], RED) for c in hosts]
                                 + [(c["bbox"], BLUE) for c in inner["cells"]],
                                 "evidence": {"outer_cell": [cell_json(outer, c) for c in hosts],
                                              "inner_table": {"id": inner["id"], "bbox": inner["bbox"],
                                                              "parent": inner.get("parent")},
                                              "inner_cell_texts_repeated_in_outer_cell": repeated}})
    return problems


def c_bbox(char):
    return [char["x0"], char["top"], char["x1"], char["bottom"]]


def cell_json(table, cell):
    return {"table_id": table["id"], **{k: cell[k] for k in ("row", "column", "row_span", "column_span", "text", "bbox")}}


def text_cell_json(table, line):
    """What the JSON says about the position of this text: the cells and slots in its band."""
    top, bottom = min(ch["top"] for ch in line), max(ch["bottom"] for ch in line)
    row_cells = [c for c in table["cells"] if c["bbox"][1] < bottom and top < c["bbox"][3]]
    rows = sorted({c["row"] for c in row_cells})
    return {"table_id": table["id"], "rows_at_this_height": rows,
            "stored_rows": {r: table["rows"][r] for r in rows},
            "cells_containing_this_text": []}


def column_edges(table):
    return sorted({c["bbox"][0] for c in table["cells"] if c["column_span"] == 1} | {table["bbox"][0]})


def group_lines(chars):
    lines = []
    for ch in sorted(chars, key=lambda c: (round(c["top"]), c["x0"])):
        if lines and abs(lines[-1][-1]["top"] - ch["top"]) < 2 and ch["x0"] - lines[-1][-1]["x1"] < 40:
            lines[-1].append(ch)
        else:
            lines.append([ch])
    return lines


def px(box, origin):
    return [(box[0] - origin[0]) * SCALE, (box[1] - origin[1]) * SCALE,
            (box[2] - origin[0]) * SCALE, (box[3] - origin[1]) * SCALE]


def draw_case(pdf_page, page_json, problems, title, out_path, earlier=()):
    """`earlier`: boxes highlighted in the "before" run, so a fixed case shows the same place."""
    tables = page_json["tables"]
    focus = [b for p in problems for b, _ in p["boxes"]] or list(earlier) or [t["bbox"] for t in tables]
    now_holding = [] if problems else [c["bbox"] for t in tables for c in t["cells"]
                                       if any(overlaps(c["bbox"], b) for b in earlier)]
    left = min([b[0] for b in focus] + [t["bbox"][0] for t in tables])
    right = max([b[2] for b in focus] + [t["bbox"][2] for t in tables])
    region = [max(0, left - 15), max(0, min(b[1] for b in focus) - 40),
              min(pdf_page.width, right + 15), min(pdf_page.height, max(b[3] for b in focus) + 40)]
    image = pdf_page.crop(region).to_image(resolution=RESOLUTION).original.convert("RGB")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for table in tables:  # every stored cell, thin grey, so the grid the JSON describes is visible
        for cell in table["cells"]:
            draw.rectangle(px(cell["bbox"], region), outline=GREY + (255,), width=1)
    for problem in problems:
        for x in problem.get("columns", []):
            x = (x - region[0]) * SCALE
            draw.line([(x, 0), (x, image.size[1])], fill=GREEN + (255,), width=2)
        for box, colour in problem["boxes"]:
            draw.rectangle(px(box, region), outline=colour + (255,), width=2 if colour == ORANGE else 3)
    for box in now_holding:
        draw.rectangle(px(box, region), outline=GREEN + (255,), width=3)
    phantoms = phantom_cells(pdf_page, tables, region)
    for box in phantoms:
        draw_dashed(draw, px(box, region), MAGENTA + (255,))
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    legend = legend_lines(problems, bool(phantoms))
    if not problems:
        title = title.replace("]", ": fixed]", 1)
    band = 40 + 26 * len(legend)
    canvas = Image.new("RGB", (max(image.size[0], 900), image.size[1] + band), "white")
    canvas.paste(image, (0, band))
    text = ImageDraw.Draw(canvas)
    text.text((12, 10), title, fill="black", font=BOLD)
    for i, (colour, line) in enumerate(legend):
        y = 42 + 26 * i
        text.rectangle([12, y + 2, 30, y + 18], outline=colour, width=3)
        text.text((40, y), line, fill="black", font=FONT)
    canvas.save(out_path)


def phantom_cells(pdf_page, tables, region):
    """Invisible light fills (cell shading) whose outline the JSON stores as a cell."""
    cells = [c["bbox"] for t in tables for c in t["cells"]]
    fills = [[r["x0"], r["top"], r["x1"], r["bottom"]] for r in pdf_page.rects
             if r["fill"] and not r["stroke"] and light(r["non_stroking_color"])
             and overlaps([r["x0"], r["top"], r["x1"], r["bottom"]], region)]
    return [f for f in fills if any(all(abs(f[i] - c[i]) < 1 for i in range(4)) for c in cells)]


def light(colour):
    values = colour if isinstance(colour, (list, tuple)) else [colour]
    return bool(values) and all(isinstance(v, (int, float)) and v > .5 for v in values)


def draw_dashed(draw, box, colour, dash=8):
    x0, y0, x1, y1 = box
    for a, b, horizontal in (((x0, y0), x1, True), ((x0, y1), x1, True), ((x0, y0), y1, False), ((x1, y0), y1, False)):
        start = a[0] if horizontal else a[1]
        for p in range(int(start), int(b), dash * 2):
            end = min(p + dash, b)
            draw.line([(p, a[1]), (end, a[1])] if horizontal else [(a[0], p), (a[0], end)], fill=colour, width=2)


def legend_lines(problems, phantoms):
    kinds = {p["kind"] for p in problems}
    lines = [(GREY, "Grey: every cell stored in the JSON")]
    if phantoms:
        lines.append((MAGENTA, "Magenta dashed: invisible white/grey shading box that the JSON stores as a cell"))
    if not kinds:
        return lines + [(GREEN, "Green: the cells that now hold this text. Each printed character has exactly one cell.")]
    if "overlapping_cells" in kinds:
        lines += [(RED, "Red: outer cell that stores the text"), (BLUE, "Blue: inner cell that stores the same text again"),
                  (ORANGE, "Orange: the printed characters stored twice")]
    if "text_without_cell" in kinds:
        lines += [(ORANGE, "Orange: printed text that sits in no JSON cell (position lost)")]
    if "span_outside_grid" in kinds:
        lines += [(RED, "Red: cell whose column_span runs past column_count"),
                  (GREEN, "Green: column edges the JSON declares")]
    if "nested_table_duplicate_text" in kinds:
        lines += [(RED, "Red: outer table cell whose text includes the inner table"),
                  (BLUE, "Blue: inner table cells holding the same text again")]
    return lines


def main(label):
    out = ROOT / "output" / "validation" / "proof" / label
    out.mkdir(parents=True, exist_ok=True)
    results, summary = {}, []
    before = ROOT / "output" / "validation" / "proof" / "before" / "evidence.json"
    earlier = {} if label == "before" or not before.exists() else         {case["case"]: case["highlighted_boxes"] for case in json.loads(before.read_text(encoding="utf-8"))["cases"]}
    for name, page_number, slug, title in CASES:
        path = next((ROOT / "pdfs").rglob(name))
        if path not in results:
            results[path] = extract_pdf(path)
        page_json = results[path]["pages"][page_number - 1]
        with pdfplumber.open(path) as pdf:
            page = pdf.pages[page_number - 1]
            problems = [p for p in find_problems(page_json, page.chars) if wanted(slug, p)]
            draw_case(page, page_json, problems, f"[{label}] {title}", out / f"{slug}.png", earlier.get(slug, ()))
        summary.append({"case": slug, "pdf": name, "page": page_number, "problems_found": len(problems),
                        "highlighted_boxes": [b for p in problems for b, _ in p["boxes"]],
                        "problems": [{k: v for k, v in p.items() if k not in ("boxes", "columns")} for p in problems]})
        print(f"{slug}: {len(problems)} problem(s)")
    (out / "evidence.json").write_text(json.dumps({"parser_version": PARSER_VERSION, "cases": summary},
                                                  ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def wanted(slug, problem):
    kind = {"overlapping_cells": "overlapping", "text_without_cell": "without_cell",
            "span_outside_grid": "span_outside", "nested_table_duplicate_text": "nested"}[problem["kind"]]
    return kind in slug


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1] if len(sys.argv) > 1 else "before")
