"""Read native PDF text and ruled tables without inventing missing values.

The raw page text and table cell geometry are the source of truth. The fields
view is a convenient interpretation of those cells, not an OCR transcription.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Callable

import pdfplumber

PARSER_VERSION = "1.2.0"
MAX_PAGES = 200
SPACER_WIDTH = 6        # cells this narrow are layout slivers, whatever they contain
EMPTY_SPACER_WIDTH = 12  # empty cells narrower than this are slivers too; real blank answers are much wider
PENDING = object()  # heading row seen; its scope is the next coded clause
CODE = re.compile(r"^((?:[A-Z]\s*)?\d+(?:\s*\.\s*\d+)+)\s*\.?(?:\s+[A-Z]\.)?$")
# The identifier after the keyword must contain a digit (T7, 4K, 6A) or be a single capital letter (annex G),
# so ordinary words ("Annexure with", "enclosurev") are not taken as references.
REFERENCE = re.compile(r"\b(?:Refer\s+)?(?:Annexure|Annex|Enclosure|Appendix)\b\s*[–\-:]?\s*"
                       r"(?-i:[A-Z]{0,2}\d[A-Z0-9]*|[A-Z]\b)(?:\s*[–\-]\s*(?-i:[A-Z0-9]+)\b)?", re.I)


class ExtractionError(ValueError):
    pass


def clean(value: str | None) -> str:
    return "\n".join(line.strip() for line in (value or "").splitlines()).strip()


def field_code(text: str) -> str | None:
    match = CODE.fullmatch(clean(text))
    return re.sub(r"\s+", "", match.group(1)).rstrip(".") if match else None


def bbox(box) -> list[float]:
    return [round(float(v), 3) for v in box]


def _table_data(table, page_number: int, index: int) -> dict:
    matrix = [[clean(v) if v is not None else None for v in row] for row in table.extract()]
    xs = sorted({round(v, 4) for c in table.cells for v in (c[0], c[2])})
    ys = sorted({round(v, 4) for c in table.cells for v in (c[1], c[3])})
    cells = []
    for row_index, row in enumerate(table.rows):
        for col_index, box in enumerate(row.cells):
            if box is None:
                continue
            x0, y0, x1, y1 = box
            cells.append({
                "row": row_index, "column": col_index,
                "row_span": sum(y0 - .01 <= y < y1 - .01 for y in ys),
                "column_span": sum(x0 - .01 <= x < x1 - .01 for x in xs),
                "text": matrix[row_index][col_index], "bbox": bbox(box),
            })
    return {"id": f"p{page_number}-t{index}", "source_page": page_number,
            "bbox": bbox(table.bbox), "role": "content", "rows": matrix,
            "row_count": len(matrix), "column_count": len(table.columns), "cells": cells}


def _active_cells(table: dict, row_index: int) -> list[dict]:
    owners = [c for c in table["cells"] if c["row"] == row_index]
    if not owners:
        return []
    middle = min(c["bbox"][1] for c in owners) + .05
    return sorted((c for c in table["cells"] if c["bbox"][1] <= middle < c["bbox"][3]),
                  key=lambda c: c["bbox"][0])


def _is_footer(cells: list[dict]) -> bool:
    # The signature block. Some forms print "Manufacturer:" outside the ruled box,
    # leaving only "Document No" and "Test agency" inside it.
    text = " ".join(c["text"] for c in cells).lower()
    return ("manufacturer:" in text or "document no" in text) and ("test agency" in text or "signature, name" in text)


def _is_spacer(cell: dict) -> bool:
    width = cell["bbox"][2] - cell["bbox"][0]
    return width <= SPACER_WIDTH or (not cell["text"] and width < EMPTY_SPACER_WIDTH)


def _value_cells(cells: list[dict], value_x: float) -> list[dict]:
    return [c for c in cells if c["bbox"][0] >= value_x - .2 and not _is_spacer(c)]


def _looks_like_heading(text: str) -> bool:
    """Words such as "Blower" or "Provided Category - 5"; not a measurement, part number, placeholder or mask."""
    text = clean(text)
    if not text or re.fullmatch(r"(?i)na|n/a|nil|yes|no|-+|[xy]+", text):
        return False
    body = re.sub(r"[\s\-–]*\d{1,2}$", "", text)
    return bool(re.search(r"[A-Za-z]{2}", body)) and not re.search(r"\d", body)


def _is_label_row(cells: list[dict], following: list[list[dict]]) -> bool:
    """Two or more heading-like cells, with one of the next rows' values sitting exactly under them."""
    if len(cells) < 2 or not all(_looks_like_heading(c["text"]) for c in cells):
        return False
    return any(len(nxt) == len(cells) and all(_header(n, cells) is not None for n in nxt) for nxt in following)


def _is_title(cells: list[dict]) -> bool:
    text = " ".join(c["text"] for c in cells)
    return bool(re.search(r"\bTable\s+\d+[A-Z]?\s+of\s+AIS", text, re.I))


def _value(cell: dict, table: dict, row_index: int, label: str | None = None,
           row_label: str | None = None) -> dict:
    return {"text": cell["text"], "column_label": label, "row_label": row_label,
            "source_page": table["source_page"], "bbox": cell["bbox"],
            "inherited_from_merged_cell": cell["row"] != row_index,
            "source_cell": {"table_id": table["id"], "row": cell["row"], "column": cell["column"]}}


def _year_headers(rows: list[list[dict]], index: int) -> list[dict]:
    """Recognise an ordered year axis and align it to the cells directly below.

    PDF borders can split a printed heading into a text cell and tiny blank
    cells. Match containment rather than requiring identical cell widths.
    Ordinary numeric answer rows are not headings.
    """
    if index + 1 >= len(rows):
        return []
    years = [c for c in rows[index] if re.fullmatch(r"(?:19|20|21)\d{2}", c["text"])]
    if len(years) < 3:
        return []
    numbers = [int(c["text"]) for c in years]
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        return []
    others = [c for c in rows[index] if c["text"] and c not in years]
    if len(others) > 1 or any(c["text"].upper() != "YEAR" for c in others):
        return []
    following = [c for c in rows[index + 1] if not _is_spacer(c)]
    if len(following) != len(years) + 1 or not following[0]["text"]:
        return []
    if following[0]["bbox"][2] > years[0]["bbox"][0] + .2:
        return []
    headers = []
    for year, value in zip(years, following[1:]):
        if not (value["bbox"][0] - .2 <= year["bbox"][0]
                and year["bbox"][2] <= value["bbox"][2] + .2):
            return []
        header = dict(year)
        header["bbox"] = [value["bbox"][0], year["bbox"][1],
                          value["bbox"][2], year["bbox"][3]]
        headers.append(header)
    return headers


def _table_heading(page, table: dict, tables: list[dict]) -> dict | None:
    """Read a nearby caption outside the ruled table, without taking another table's text."""
    x0, top, x1, _ = table["bbox"]
    preceding = [t["bbox"][3] for t in tables if t["bbox"][3] <= top
                 and t["bbox"][0] < x1 and t["bbox"][2] > x0]
    strip_top = max(page.bbox[1], top - 24, max(preceding, default=0))
    if strip_top >= top:
        return None
    words = page.crop((x0, strip_top, x1, top)).extract_words()
    if not words:
        return None
    bottom = max(w["bottom"] for w in words)
    line = sorted((w for w in words if abs(w["bottom"] - bottom) < 2), key=lambda w: w["x0"])
    return {"text": " ".join(w["text"] for w in line),
            "bbox": bbox((min(w["x0"] for w in line), min(w["top"] for w in line),
                          max(w["x1"] for w in line), bottom))}


def _interpret_table(table: dict, records: list[dict], context: dict,
                     heading: dict | None = None) -> None:
    rows = [_active_cells(table, r) for r in range(table["row_count"])]
    if rows and _is_footer(rows[0]):
        table["role"] = "footer"
        return
    code_rows = []
    for r, cells in enumerate(rows):
        nonempty = [c for c in cells if c["text"]]
        if nonempty and field_code(nonempty[0]["text"]):
            code_rows.append((r, nonempty[0], cells))
    coded = bool(code_rows)
    # Use the repeated description/value boundary, rather than a column index:
    # Word-generated PDFs introduce narrow spacer columns and split cells.
    boundaries = []
    for _, code_cell, cells in code_rows:
        after = [c for c in cells if c["bbox"][0] >= code_cell["bbox"][2] - .1]
        desc = next((c for c in after if c["text"]), None)
        if desc and desc["bbox"][2] < table["bbox"][2] - 5:
            boundaries.append(round(desc["bbox"][2], 1))
    value_x = Counter(boundaries).most_common(1)[0][0] if boundaries else None
    headers: list[dict] = []
    headers_row = None
    headers_scope = None  # code whose sub-clauses a heading field applies to
    last_row = None
    previous = context.get("previous") if coded else None
    year_grid = False
    grid_section = None

    def next_values(index: int, count: int = 3) -> list[list[dict]]:
        following = [r for r in rows[index + 1:] if any(c["text"] for c in r)][:count]
        return [_value_cells(r, value_x) for r in following] if value_x is not None else []

    for row_index, cells in enumerate(rows):
        if _is_footer(cells):
            # Some PDFs connect the signature block to the main table.
            # Everything after this row is footer content, retained in raw tables.
            break
        if _is_title(cells):
            continue
        nonempty = [c for c in cells if c["text"]]
        if not nonempty:
            continue
        if not coded:
            year_headers = _year_headers(rows, row_index)
            if year_headers:
                headers, headers_row, headers_scope = year_headers, row_index, None
                year_grid = True
                if grid_section is None and heading:
                    grid_section = {
                        "id": f"f{len(records) + 1:05d}", "field_id": None,
                        "parent_id": None, "level": 1, "kind": "section",
                        "description": heading["text"], "values": [],
                        "source_page": table["source_page"], "table_id": table["id"],
                        "row": None, "bbox": heading["bbox"],
                        "continuation_rows": [], "references": [],
                    }
                    records.append(grid_section)
                continue
        prev_row, last_row = last_row, row_index
        code_cell = nonempty[0] if field_code(nonempty[0]["text"]) else None
        if coded and (not code_cell or code_cell["row"] != row_index):
            # A row of column headings without a code (e.g. Blower | Low-Cost Heater | AC).
            if value_x is not None:
                own_values = _value_cells([c for c in cells if c["row"] == row_index], value_x)
                if _is_label_row(own_values, next_values(row_index)):
                    # Scoped to the clause family that follows (set below).
                    headers, headers_row, headers_scope = own_values, row_index, PENDING
            if previous:
                own = [c for c in cells if c["row"] == row_index and c["text"]]
                previous["continuation_rows"].append({
                    "source_page": table["source_page"], "table_id": table["id"],
                    "row": row_index, "cells": [c["text"] for c in own],
                })
                # Expand true row-spanning labels (e.g. CC, FSD and HSD).
                desc_box = context.get("description_bbox")
                if code_cell and desc_box and any(c["bbox"] == desc_box for c in cells):
                    right = _value_cells(cells, value_x) if value_x is not None else []
                    row_label = " / ".join(c["text"] for c in own if desc_box[2] - .2 <= c["bbox"][0] < (value_x or 0) - .2) or None
                    previous["values"].extend(_value(c, table, row_index, _header(c, headers), row_label) for c in right)
            continue
        if code_cell:
            code = field_code(code_cell["text"])
            after = [c for c in cells if c["bbox"][0] >= code_cell["bbox"][2] - .1]
            description = next((c for c in after if c["text"]), None)
            if description is None:
                continue
        else:
            code = None
            description = nonempty[0]
        right = [c for c in cells if c["bbox"][0] >= description["bbox"][2] - .1]
        # Ignore narrow spacer columns and trailing blank slivers.
        right = [c for c in right if not _is_spacer(c)]
        if coded and value_x is not None:
            row_labels = [c for c in right if c["bbox"][0] < value_x - .2]
            right = [c for c in right if c["bbox"][0] >= value_x - .2]
        else:
            row_labels = []
        row_label = " / ".join(c["text"] for c in row_labels if c["text"]) or None
        if year_grid:
            # A different layout (e.g. the ordinary VIN details below the grid)
            # ends this axis. Do not carry year headings into unrelated fields.
            if len(right) != len(headers) or any(_header(c, headers) is None for c in right):
                headers, headers_row, headers_scope = [], None, None
                year_grid, grid_section = False, None
            else:
                row_label = description["text"]
        is_section = bool(code and code.endswith(".0")) or (not year_grid and not any(c["text"] for c in right))
        # Headings end at the next .0 code, unless the heading row sits directly above it.
        # Headings taken from a field only cover that field's own sub-clauses.
        if code and code.endswith(".0") and not (headers_row is not None and headers_row == prev_row):
            headers, headers_row, headers_scope = [], None, None
        if headers_scope is PENDING and code:
            # The heading belongs to the clause family of the next code: E28.0 → E28, D7.5.1 → D7.5.
            headers_scope = code[:-2] if code.endswith(".0") else code.rsplit(".", 1)[0]
        if headers_scope and headers_scope is not PENDING and not (code == headers_scope or (code or "").startswith(headers_scope + ".")):
            headers, headers_row, headers_scope = [], None, None
        if is_section and len(right) > 1 and any(re.search(r"\b(?:WB|GVW|variant|gear|ratio)\b", c["text"], re.I) for c in right):
            headers, headers_row, headers_scope = right, row_index, None
        record = {
            "id": f"f{len(records) + 1:05d}", "field_id": code,
            "parent_id": grid_section["id"] if year_grid and grid_section else None,
            "level": 2 if year_grid and grid_section else len(code.split(".")) if code else 1,
            "kind": "section" if is_section else "field", "description": description["text"],
            "values": [_value(c, table, row_index, None if is_section else _header(c, headers), row_label) for c in right],
            "source_page": table["source_page"], "table_id": table["id"], "row": row_index,
            "bbox": bbox((min(c["bbox"][0] for c in cells), min(c["bbox"][1] for c in cells),
                          max(c["bbox"][2] for c in cells), max(c["bbox"][3] for c in cells))),
            "continuation_rows": [], "references": [],
        }
        records.append(record)
        # A field whose values are headings for the rows below it (e.g. E15.3 "Provided Category - 5 | 6").
        if code and value_x is not None and not headers and not is_section and _is_label_row(right, next_values(row_index, 1)):
            headers, headers_row, headers_scope = right, row_index, code
        previous = record
        context.update(previous=record, description_bbox=description["bbox"])


def _header(cell: dict, headers: list[dict]) -> str | None:
    for header in headers:
        left = max(header["bbox"][0], cell["bbox"][0])
        right = min(header["bbox"][2], cell["bbox"][2])
        width = max(header["bbox"][2] - header["bbox"][0], cell["bbox"][2] - cell["bbox"][0])
        if width > 0 and (right - left) / width > .8:
            return header["text"]
    return None


def _hierarchy(records: list[dict]) -> None:
    seen: dict[str, dict] = {}
    section = None
    for record in records:
        code = record["field_id"]
        if code:
            parts = code.split(".")
            # A1.1 belongs to A1.0; 1.2.1 belongs to 1.2, then 1.0.
            candidates = [".".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)]
            parent = next((seen[k] for stem in candidates for k in (stem, stem + ".0") if k in seen), None)
            if parent:
                record["parent_id"] = parent["id"]
                record["level"] = parent["level"] + 1
            else:
                record["level"] = 1
            seen[code] = record
        elif record["parent_id"] is not None:
            # Lookup grid rows already have a parent determined from their caption.
            pass
        elif section and record["kind"] == "section" and not section["field_id"]:
            # Without codes, consecutive headings are siblings, not nested.
            record["parent_id"] = section["parent_id"]
            record["level"] = section["level"]
        elif section:
            record["parent_id"] = section["id"]
            record["level"] = section["level"] + 1
        if record["kind"] == "section" and not (record["table_id"] and record["row"] is None):
            section = record
        text = record["description"] + " " + " ".join(v["text"] for v in record["values"])
        record["references"] = list(dict.fromkeys(m.group(0) for m in REFERENCE.finditer(text)))


def _text_fields(text: str, page_number: int, records: list[dict]) -> None:
    # Unruled text fallback is deliberately marked for review in the result.
    for line in text.splitlines():
        match = re.match(r"^((?:[A-Z]\s*)?\d+(?:\.\d+)+)\.?\s+(.+)$", line)
        if not match:
            continue
        records.append({"id": f"f{len(records) + 1:05d}", "field_id": match.group(1),
                        "parent_id": None, "level": 1, "kind": "field", "description": match.group(2),
                        "values": [], "source_page": page_number, "table_id": None, "row": None,
                        "bbox": None, "continuation_rows": [], "references": []})


def extract_pdf(path: str | Path, filename: str | None = None,
                progress: Callable[[int, int], None] | None = None) -> dict:
    path = Path(path)
    try:
        pdf = pdfplumber.open(path)
    except Exception as exc:
        raise ExtractionError("This PDF cannot be read. It may be damaged or password protected.") from exc
    pages, records, warnings = [], [], []
    context: dict = {}
    with pdf:
        count = len(pdf.pages)
        if not 1 <= count <= MAX_PAGES:
            raise ExtractionError(f"Upload a PDF with 1 to {MAX_PAGES} pages.")
        for number, page in enumerate(pdf.pages, 1):
            raw_text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            page_warnings = []
            tables = [_table_data(t, number, i) for i, t in enumerate(page.find_tables(), 1)]
            for table in tables:
                _interpret_table(table, records, context, _table_heading(page, table, tables))
            content_tables = [t for t in tables if t["role"] == "content"]
            if not content_tables and len(raw_text.strip()) >= 40:
                _text_fields(raw_text, number, records)
                page_warnings.append("No ruled content table detected. Use raw text to review this page.")
            requires_ocr = len(raw_text.strip()) < 40
            if requires_ocr:
                page_warnings.append("Little or no selectable text. OCR is required to transcribe this page.")
            images = [{"id": f"p{number}-image{i}", "bbox": bbox((im["x0"], im["top"], im["x1"], im["bottom"])),
                       "transcribed": False} for i, im in enumerate(page.images, 1)]
            if images:
                page_warnings.append("Embedded images are referenced by location; their visual content is not transcribed.")
            pages.append({"page_number": number, "width": round(page.width, 3), "height": round(page.height, 3),
                          "raw_text": raw_text, "tables": tables, "images": images,
                          "requires_ocr": requires_ocr, "warnings": page_warnings})
            warnings.extend({"source_page": number, "message": w} for w in page_warnings)
            if progress:
                progress(number, count)
            page.close()
    _hierarchy(records)
    first_text = pages[0]["raw_text"]
    table_match = re.search(r"Table\s+(\d+[A-Z]?)\s+of\s+AIS[\s-]*0*07", first_text, re.I)
    part_match = re.search(r"PART\s+([A-Z])\s*[–-]\s*([^\n]+)", first_text)
    date_match = re.search(r"Date:\s*(\d{1,2}[./]\d{1,2}[./]\d{4})", first_text)
    form_title = next((f["description"] for f in records if f["source_page"] == 1
                       and f["kind"] == "section"
                       and re.search(r"SPECIFICATION|DETAILS OF", f["description"])), None)
    return {
        "schema_version": "1.0", "parser_version": PARSER_VERSION,
        "document": {"filename": filename or path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "page_count": len(pages), "table_number": table_match.group(1) if table_match else None,
                     "standard": "AIS-007" if table_match else None,
                     "part": part_match.group(1) if part_match else None,
                     "title": part_match.group(2).strip() if part_match else form_title or next((line for line in first_text.splitlines() if "SPECIFICATION" in line or "DETAILS OF" in line), None),
                     "document_date": date_match.group(1) if date_match else None},
        "extraction": {"method": "native_text_and_ruled_tables", "generated_at": datetime.now(timezone.utc).isoformat(),
                       "status": "needs_review" if warnings else "complete", "field_count": len(records),
                       "table_count": sum(len(p["tables"]) for p in pages),
                       "requires_ocr_pages": [p["page_number"] for p in pages if p["requires_ocr"]],
                       "warnings": warnings},
        "fields": records, "pages": pages,
    }
