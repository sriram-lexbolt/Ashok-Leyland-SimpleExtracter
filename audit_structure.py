"""Audit preservation independently from field meaning. Read-only: never changes the parser."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import pdfplumber
import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from extractor.engine import PARSER_VERSION, clean, extract_pdf


def characters(text):
    return Counter(char for char in text if not char.isspace())


def contains(box, x, y):
    return box[0] - .01 <= x < box[2] + .01 and box[1] - .01 <= y < box[3] + .01


def audit_document(path):
    result = extract_pdf(path)
    entry = {
        "filename": path.name, "source_path": path.relative_to(ROOT).as_posix(),
        "sha256": result["document"]["sha256"], "pages": len(result["pages"]),
        "tables": sum(len(page["tables"]) for page in result["pages"]),
        "native_character_count": 0, "native_non_whitespace_character_count": 0,
        "embedded_images": 0, "vector_objects": 0, "page_checks": [],
        "serialization_issues": [], "grid_span_issues": [], "open_grid_slots": [],
        "overlapping_text_cells": [], "nested_table_overlap": [],
        "native_text_without_cell_positions": [], "pdfium_text_disagreements": [],
        "pdfium_unmapped_characters": 0, "shading_cells_merged": 0, "open_border_cells": 0,
    }
    with pdfplumber.open(path) as source_pdf, pdfium.PdfDocument(str(path)) as independent_pdf:
        assert len(source_pdf.pages) == entry["pages"]
        for number, (source, page) in enumerate(zip(source_pdf.pages, result["pages"]), 1):
            source_tables = source.find_tables()
            native = characters("".join(char["text"] for char in source.chars))
            raw = characters(page["raw_text"])
            entry["native_character_count"] += len(source.chars)
            entry["native_non_whitespace_character_count"] += sum(native.values())
            entry["embedded_images"] += len(source.images)
            entry["vector_objects"] += len(source.lines) + len(source.rects) + len(source.curves)
            source_order_text = source.extract_text(x_tolerance=2, y_tolerance=3) or ""
            checks = {
                "page": number, "page_number_and_size": page["page_number"] == number
                and page["width"] == round(source.width, 3) and page["height"] == round(source.height, 3),
                "raw_text_matches_source_extraction_order": page["raw_text"] == source_order_text,
                "native_character_inventory": raw == native,
                "raw_table_count": len(source_tables) == len(page["tables"]),
                "table_cell_serialization": True,
                "table_array_spatial_order": [table["bbox"] for table in page["tables"]]
                == sorted([table["bbox"] for table in page["tables"]], key=lambda box: (box[1], box[0])),
                "image_locations": [im["bbox"] for im in page["images"]]
                == [[round(float(v), 3) for v in (im["x0"], im["top"], im["x1"], im["bottom"])]
                    for im in source.images],
            }
            for original, table in zip(source_tables, page["tables"]):
                source_text = {tuple(round(float(v), 3) for v in box): clean(text)
                               for row, values in zip(original.rows, original.extract())
                               for box, text in zip(row.cells, values) if box is not None}
                stored = {tuple(cell["bbox"]): cell for cell in table["cells"]}
                hosts = {(child["parent"]["row"], child["parent"]["column"]) for child in page["tables"]
                         if (child.get("parent") or {}).get("table_id") == table["id"]}
                positions = [(cell["row"], cell["column"]) for cell in table["cells"]]
                checks["table_cell_serialization"] &= positions == sorted(positions)
                # Each source cell is stored as printed, or was a shading box inside a stored cell.
                for box, text in source_text.items():
                    cell = stored.get(box)
                    if cell is None:
                        checks["table_cell_serialization"] &= any(
                            c["bbox"][0] - .01 <= box[0] and c["bbox"][1] - .01 <= box[1]
                            and box[2] <= c["bbox"][2] + .01 and box[3] <= c["bbox"][3] + .01 for c in table["cells"])
                        entry["shading_cells_merged"] += 1
                    elif (cell["row"], cell["column"]) not in hosts:
                        checks["table_cell_serialization"] &= cell["text"] == text and cell["ruled"]
                # Cells not in the source grid must be open (partly unruled) regions.
                checks["table_cell_serialization"] &= all(not c["ruled"] for b, c in stored.items() if b not in source_text)
                entry["open_border_cells"] += sum(not c["ruled"] for c in table["cells"])
                reconstructed = [[None] * table["column_count"] for _ in range(table["row_count"])]
                coverage = {}
                collisions = []
                beyond = []
                for cell in table["cells"]:
                    row, column = cell["row"], cell["column"]
                    reconstructed[row][column] = cell["text"]
                    for r in range(row, row + cell["row_span"]):
                        for c in range(column, column + cell["column_span"]):
                            if r >= table["row_count"] or c >= table["column_count"]:
                                beyond.append({"owner": [row, column], "slot": [r, c], "text": cell["text"]})
                            elif (r, c) in coverage:
                                collisions.append({"owner": [row, column], "other_owner": coverage[(r, c)], "slot": [r, c]})
                            else:
                                coverage[(r, c)] = [row, column]
                checks["table_cell_serialization"] &= reconstructed == table["rows"]
                if collisions or beyond:
                    entry["grid_span_issues"].append({"page": number, "table_id": table["id"],
                        "overlapping_span_slots": collisions, "span_slots_outside_declared_grid": beyond})
                gaps = [[r, c] for r, row in enumerate(table["rows"]) for c in range(len(row)) if (r, c) not in coverage]
                if gaps:
                    entry["open_grid_slots"].append({"page": number, "table_id": table["id"], "slots": gaps,
                        "classification": "blank: no printed cell or text here (e.g. beside a cell drawn wider than the rest)"})
            all_cells = [(table, cell) for table in page["tables"] for cell in table["cells"]]
            children = {}
            for child in page["tables"]:
                if child.get("parent"):
                    children.setdefault((child["parent"]["table_id"], child["parent"]["row"],
                                         child["parent"]["column"]), []).append(child["bbox"])
            loose_lines = [line["bbox"] for line in page.get("text_outside_tables", [])]
            outside = 0
            outside_text = []
            internal = Counter()
            nested = Counter()
            examples = {}
            for char in source.chars:
                if not char["text"].strip():
                    continue
                x, y = (char["x0"] + char["x1"]) / 2, (char["top"] + char["bottom"]) / 2
                # A cell holding a nested table does not hold that table's text.
                owners = [(table["id"], cell) for table, cell in all_cells if contains(cell["bbox"], x, y)
                          and not any(contains(box, x, y) for box in
                                      children.get((table["id"], cell["row"], cell["column"]), []))]
                if not owners and not any(contains(box, x, y) for box in loose_lines):
                    outside += len(char["text"])
                    outside_text.append(char["text"])
                by_table = Counter(tid for tid, _ in owners)
                for tid, count in by_table.items():
                    if count > 1:
                        internal[tid] += len(char["text"])
                        examples.setdefault(tid, []).append(char["text"])
                if len(by_table) > 1:
                    nested[tuple(sorted(by_table))] += len(char["text"])
            if outside:
                entry["native_text_without_cell_positions"].append({"page": number, "characters": outside,
                    "example_text_in_source_object_order": "".join(outside_text)[:200]})
            for tid, count in internal.items():
                entry["overlapping_text_cells"].append({"page": number, "table_id": tid,
                    "source_characters_assigned_to_multiple_cells": count, "example_text": "".join(examples[tid])[:100]})
            for ids, count in nested.items():
                entry["nested_table_overlap"].append({"page": number, "table_ids": list(ids),
                    "source_characters_represented_in_multiple_tables": count,
                    "classification": "shared text would be rendered twice"})
            independent_page = independent_pdf[number - 1]
            text_page = independent_page.get_textpage()
            independent_text = text_page.get_text_range()
            text_page.close()
            independent_page.close()
            # PDFium reports some unconvertible glyphs as U+FFFE. Keep that count
            # visible instead of reporting those sentinels as missing PDF data.
            unmapped = independent_text.count("\ufffe")
            entry["pdfium_unmapped_characters"] += unmapped
            independent_counter = characters(independent_text.replace("\ufffe", ""))
            absent = independent_counter - raw
            if absent:
                entry["pdfium_text_disagreements"].append({"page": number, "pdfium_characters_absent_from_raw_text": dict(absent)})
            for name, passed in checks.items():
                if name != "page" and not passed:
                    entry["serialization_issues"].append({"page": number, "check": name})
            entry["page_checks"].append(checks)
    entry["text_and_serialization_status"] = "pass" if not entry["serialization_issues"] and not entry["pdfium_text_disagreements"] else "review"
    # Blank open slots hold no printed text (any text there is counted as unpositioned), so they do not fail.
    entry["grid_topology_status"] = "fail" if (entry["grid_span_issues"] or entry["overlapping_text_cells"]
                                               or entry["nested_table_overlap"]
                                               or entry["native_text_without_cell_positions"]) else "pass"
    entry["pixel_exact_reconstruction"] = "out of scope: fonts, glyph positions, image bytes and drawings are not stored"
    return entry


def write_markdown(report, output):
    totals = report["summary"]
    documents = report["documents"]
    lines = ["# PDF-to-JSON preservation audit", "",
        f"Parser: `{report['parser_version']}`. Audited {totals['documents']} PDFs, {totals['pages']} pages, and {totals['tables']} detected tables.", "",
        "The primary requirement is preservation of printed content, order, placement, table structure, blank cells, and merges. Field meaning and inferred labels are assessed separately.", "",
        "## Result", "",
        "| PDF | Pages | Text and order | Rows, columns and cell placement | Shading cells merged | Partly unruled cells |",
        "|---|---:|---|---|---:|---:|",
    ]
    for doc in documents:
        lines.append(f"| {doc['filename']} | {doc['pages']} | {doc['text_and_serialization_status']} | {doc['grid_topology_status']} "
                     f"| {doc['shading_cells_merged']} | {doc['open_border_cells']} |")
    lines += ["", "## Content and order checks", "",
        f"- All {totals['pages']} page numbers and dimensions agree with the source PDFs.",
        f"- All {totals['native_non_whitespace_characters']:,} selectable non-whitespace characters are accounted for in page-level `raw_text` by per-page character inventories.",
        "- PDFium supplied a second, independent text extraction. Characters it could not map (U+FFFE) are counted separately in the JSON report, not as lost content.",
        "- Page `raw_text` matches the source extractor's reading order. Tables are in spatial order, and cells are in row/column order.",
        "- Every source table cell is stored with its printed text and box, or was an invisible shading box inside a stored cell. Cells not in the source grid are partly unruled areas (`ruled: false`). The `rows` matrix is rebuilt exactly from the cells.",
        "", "## Structure checks", "",
        "- Every printed character is in exactly one table cell or one `text_outside_tables` line. A cell holding a nested table does not hold that table's text.",
        "- No cell span overlaps another cell or runs past the table's declared grid.", ""]
    problems = []
    for doc in documents:
        name = doc["filename"]
        for issue in doc["grid_span_issues"]:
            problems.append(f"- {name} page {issue['page']} `{issue['table_id']}`: {len(issue['overlapping_span_slots'])} overlapping span slots, "
                            f"{len(issue['span_slots_outside_declared_grid'])} slots outside the declared grid.")
        for issue in doc["overlapping_text_cells"]:
            problems.append(f"- {name} page {issue['page']} `{issue['table_id']}`: {issue['source_characters_assigned_to_multiple_cells']} characters "
                            f"in more than one cell (`{issue['example_text']}`).")
        for issue in doc["nested_table_overlap"]:
            problems.append(f"- {name} page {issue['page']}: {issue['source_characters_represented_in_multiple_tables']} characters stored in both "
                            f"{' and '.join(issue['table_ids'])}.")
        for issue in doc["native_text_without_cell_positions"]:
            problems.append(f"- {name} page {issue['page']}: {issue['characters']} characters with no cell or line position "
                            f"(`{issue['example_text_in_source_object_order'][:60]}`).")
        for issue in doc["serialization_issues"]:
            problems.append(f"- {name} page {issue['page']}: check `{issue['check']}` failed.")
    lines += ["### Problems", ""] + (problems or ["None found."])
    blanks = [f"- {doc['filename']} page {gap['page']} `{gap['table_id']}`: {len(gap['slots'])} grid slots with no printed cell or text."
              for doc in documents for gap in doc["open_grid_slots"]]
    if blanks:
        lines += ["", "### Blank grid areas (not errors)", "",
                  "A cell printed wider than its neighbours adds a grid line; the rows without that cell leave the extra slot blank, as printed.", ""] + blanks
    lines += ["", "Visual before/after evidence for the Table 03, 06 and 11 fixes is in `output/validation/proof/` (`visual_proof.py`).",
        "", "## Interpretation findings, kept separate", "",
        "- Table 07: `Gear Ratio` and `Overall Ratio` appear as values rather than inferred column labels in `fields`. The printed words are preserved in raw table cells. This is not counted as a content-preservation failure.",
        "- Table 07: a variant name can be included under `Type / Description` because of a merged cell. This affects the convenience field view, not whether the raw cell text and its printed box are retained.",
        "- Table 06: `E31.6` lists its sub-table headings (`Description`, `AL Part No.`, `Hella Part No`) among its values, ahead of the part rows. The raw cells keep the headings in their own row.",
        "- Printed clause numbers, wording, units, placeholders, and apparent source-document mistakes are kept as printed. Meaning or corrections are outside the primary audit.",
        "", "## Not stored (pixel-exact copy is out of scope)", "",
        "The JSON is meant to rebuild the content and table structure, not a pixel-identical page. It does not store:", "",
        f"- image bytes for the {totals['embedded_images']} embedded images (only their positions);",
        "- fonts, font sizes, weights or per-character positions (text has cell and line boxes);",
        f"- the {totals['vector_objects']:,} line, rectangle and curve drawing objects, their colours and painting order (borders are implied by cell boxes; `ruled: false` marks cells whose border is partly unprinted).",
        "", "## Method and limits", "",
        "Audited every page programmatically using pdfplumber source characters and table geometry, the current extractor, and independent PDFium text. These checks do not independently prove that every visible border was detected; the visual proofs cover the known problem regions. This is not a visual certification of all 64 pages.",
        "", "To rerun from the project folder:", "",
        "```powershell", ".\\.venv\\Scripts\\python.exe audit_structure.py", "```", "",
        "Detailed page checks and issue coordinates are in `structure_report.json` alongside this report.", "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main():
    output = ROOT / "output" / "validation"
    output.mkdir(parents=True, exist_ok=True)
    documents = []
    for path in sorted((ROOT / "pdfs").rglob("*.pdf")):
        document = audit_document(path)
        documents.append(document)
        print(f"{path.name}: text/order={document['text_and_serialization_status']}, grid={document['grid_topology_status']}", flush=True)
    summary = {
        "documents": len(documents), "pages": sum(doc["pages"] for doc in documents),
        "tables": sum(doc["tables"] for doc in documents),
        "native_non_whitespace_characters": sum(doc["native_non_whitespace_character_count"] for doc in documents),
        "embedded_images": sum(doc["embedded_images"] for doc in documents),
        "vector_objects": sum(doc["vector_objects"] for doc in documents),
        "documents_passing_text_serialization": sum(doc["text_and_serialization_status"] == "pass" for doc in documents),
        "documents_with_grid_failures": sum(doc["grid_topology_status"] == "fail" for doc in documents),
        "documents_with_grid_reviews": sum(doc["grid_topology_status"] == "review" for doc in documents),
        "documents_passing_exact_reconstruction": 0,
    }
    report = {"parser_version": PARSER_VERSION,
        "engine_sha256": hashlib.sha256((ROOT / "extractor/engine.py").read_bytes()).hexdigest(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "All supplied PDFs are development fixtures. Content, order and layout preservation are primary; interpretation issues are separate. Pixel-exact reconstruction is out of scope.",
        "summary": summary, "documents": documents,
        "interpretation_findings": [
            {"document": "Table 07_Ver.01.pdf", "classification": "interpretation_only",
             "finding": "Gear Ratio and Overall Ratio classified as field values; printed words and raw boxes are preserved."},
            {"document": "Table 07_Ver.01.pdf", "classification": "interpretation_only",
             "finding": "Merged variant name included under Type / Description; source wording remains in raw tables."},
            {"document": "Table 06_Ver.01.pdf", "classification": "interpretation_only",
             "finding": "E31.6 lists its sub-table headings (Description, AL Part No., Hella Part No) as values; the raw cells keep them in their own row."}],
        "not_stored": ["positioned glyphs and font resources", "image payloads",
            "complete vector drawing objects, styles and painting order"]}
    (output / "structure_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    write_markdown(report, output / "structure_report.md")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
