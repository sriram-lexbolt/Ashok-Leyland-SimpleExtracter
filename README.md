# Jags AL Data Extracter

A small local application for uploading technical specification PDFs, reviewing extracted content beside the source pages, and downloading JSON. It supports batches of up to 10 PDFs, individual JSON downloads, and a batch ZIP.

## Run on Windows

Python 3.11 or newer is required. **Double-click `start.cmd`** to launch the application. It creates the local Python environment and installs missing dependencies automatically, then opens the application in your default browser once the server is ready. Keep the launcher window open while using the app; press Ctrl+C to stop it. First-time setup needs internet access.

Windows does not normally execute `.ps1` files by double-clicking them. The `start.cmd` launcher runs `start.ps1` with an execution-policy setting that applies only to that process.

You can also start it from PowerShell in this folder:

```powershell
.\start.cmd
```

To choose another port, run `.\start.cmd -Port 8001`. To reinstall dependencies, run `.\start.cmd -Install`. If you prefer to start it manually, use the equivalent commands:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Use `.\start.ps1 -Port 8001` to choose another port. The application binds to the local computer. There are no API keys, cloud calls, model downloads, or GPU requirements during extraction. Dependency installation needs internet access.

## What is extracted

- Document filename, hash, page count, AIS table number, part, title, and printed date where detected.
- Printed field identifiers such as `A1.6`, `B1.1`, and `1.2.1`, normalized to remove spacing and trailing periods.
- Field descriptions and values, preserving units, punctuation, placeholders (`NA`, `-`, `--`), and empty cells.
- Parent field links, references to annexures/enclosures, and source page/cell coordinates.
- Original table grids, unique cells, row/column spans, and page text.
- Locations of embedded images and explicit review notes for pages requiring OCR.

Multiple values stay in source order. Some development layouts also receive variant labels (for example, `2490 WB` and `2640 WB`). Cells spanning several rows can supply a shared value; `inherited_from_merged_cell` and `source_cell` make that traceable. Embedded subtables and continuation rows remain available under their owning field and in the raw tables.

This version reads selectable PDF text and ruled tables using pdfplumber. **It does not transcribe scanned pages or diagrams.** Such pages/content are flagged for review. Fields from unruled text are a conservative fallback; the full page text remains available.

### Changes in parser v1.3.0 (schema 1.1)

Structure fixes, so every printed character is stored exactly once and has a position. Before/after images for each case are in `output/validation/proof/`; regenerate them with `visual_proof.py before` or `visual_proof.py after`.

- Word shades a cell's text area slightly inside its borders. That invisible shading box was read as a second cell inside the real one, so one printed value was stored twice (Table 06 page 5 `-`, page 9 `Optional`). A cell that lies inside another cell and is only a shading box is now dropped.
- Some cells are printed with part of their border missing (Table 06 page 8 prints no left border beside `E 22.4`; page 9's `E 31.6` and `Identification No. / Part No.` cells have no lower borders). Text there had no cell. These areas now become cells with `ruled: false`, joined across grid lines that are not printed.
- Row and column numbers come from every printed border line. Table 11 page 1 draws the variant cell wider than the rest, so the table now has a third, narrow column; the variant spans columns 1 and 2, and the other rows leave column 2 blank. Previously `column_span: 2` pointed past a two-column grid.
- A table printed inside another table's cell records it in `parent` (Table 03 pages 7 and 16). The containing cell keeps only its own words, such as "Seat Identification No. / Part No/Drawing Number.:", instead of a copy of the inner table's text.
- `text_outside_tables` lists printed lines that are in no table cell (captions, the "Manufacturer:" line above Table 07's signature box) with their positions.

### Changes in parser v1.2.0

- Table 11's two uncoded code grids now retain their captions: year of production is Digit 10 in VIN, and month of production is Digit 12. Every code has its printed year in `column_label` and `CODE` or its month in `row_label`. For example, the year code for 2026 is `T`, while January 2026 is `S` and January 2041 is `A`.
- Repeated year headings switch the labels from 2026–2040 to 2041–2055. Heading rows supply context instead of becoming fields named `YEAR`, `2026`, or `2041`. Grid rows link to their caption through `parent_id`; the ordinary VIN details below the grid keep their own scope.
- Year headings are matched by cell geometry even when narrow blank columns split their borders. The printed codes and their original source cells are preserved, including unusual entries. The full multiline form title is retained.
- Regression tests check all 30 year codes, all 360 month codes, all nine ordinary fields, source links, and the upload/download path. These checks validate this reviewed document; they do not measure accuracy on unseen PDFs.

### Changes in parser v1.1.0

- Empty spacer cells narrower than 12 pt are no longer reported as blank values (v1.0 kept a 7 pt sliver in Table 06 E28.4 and E29.4, and blanks inside the Table 11 code grids). Filled cells are only dropped at 6 pt or narrower, as before.
- Column headings are also taken from a heading row without a clause number (Table 06 "Blower / Low-Cost Heater / AC") and from a field whose values are headings for its sub-clauses (Table 06 E15.3 "Provided Category - 5 / 6", Table 03 B3.1 "APOLLO / CEAT"). Headings must be words, not measurements, part numbers, placeholders or masked text, and they apply only to their own clause family.
- A signature box with "Document No" and "Test agency" is recognised as the footer even when "Manufacturer:" is printed outside it (Table 07 pages 1–3 no longer produce two junk records each).
- On forms without clause numbers, consecutive section headings are siblings instead of nesting inside each other (Table 07 depth drops from 28 to 2).
- A reference needs an identifier with a digit or a single capital letter, so phrases such as "Annexure with" or "Annexure to" are no longer listed.

### Known issues

- Other forms without clause numbers still have incomplete heading inference (Table 07 "Gear ratio" lists `Gear Ratio | Overall Ratio` as values). Table 11's ordered year grids are handled separately using their physical alignment.
- Merged cells are shared wherever they physically reach. Table 07's variant "Type / Description" receives the variant name; the value is marked `inherited_from_merged_cell`.
- Clause numbers are copied as printed. Table 06 prints E10.2 and E10.3 under E13.0, so they are linked to E10.0.
- References are recorded as text and are not linked to the annexure pages or other documents.
- Text printed outside ruled tables is listed with its position in `text_outside_tables`, but is not turned into fields, except nearby captions of recognised year grids, which also become section records.
- Any embedded image, including a logo, sets the document status to `needs_review`.

Review the Tables view when interpreting variants.

The extraction uses the earlier project's idea of deterministic clause regexes and parent relationships, adapted for these AIS forms. The new schema and CPU-only extraction are independent of the original GPU/OCR and AI labeling services. Reference reviewed: [PaddleOCR-Reggex-Experiment](https://github.com/sriram403/PaddleOCR-Reggex-Experiment), commit `10276a86fe7c29b34f245622eb63af686e1734ff`. A read-only clone is in `reference/`.

## JSON output

Every PDF produces one JSON file with the same structure. The keys never change from PDF to PDF; only the number of items in lists and some values (which can be `null` when the PDF does not provide them) differ. Examples below are taken from the supplied Table 02, Table 03 and Table 4E files.

### Overview

```
{
  "schema_version": "1.1",
  "parser_version": "1.3.0",
  "document":   { filename, sha256, page_count, table_number, standard, part, title, document_date },
  "extraction": { method, generated_at, status, field_count, table_count, requires_ocr_pages, warnings[] },
  "fields": [
    { id, field_id, parent_id, level, kind, description, source_page, table_id, row, bbox,
      values: [ { text, column_label, row_label, source_page, bbox, inherited_from_merged_cell, source_cell } ],
      continuation_rows: [ { source_page, table_id, row, cells } ],
      references: [ ... ] }
  ],
  "pages": [
    { page_number, width, height, raw_text, requires_ocr, warnings[],
      tables: [ { id, source_page, bbox, role, parent, rows, row_count, column_count,
                  cells: [ { row, column, row_span, column_span, text, bbox, ruled } ] } ],
      text_outside_tables: [ { text, bbox } ],
      images: [ { id, bbox, transcribed } ] }
  ]
}
```

`fields` is the interpreted view (one record per form row). `pages` is the evidence: the page text and every table cell as found, so any field can be checked against it.

Conventions: page numbers start at 1; table row and column numbers start at 0. A `bbox` is `[x0, top, x1, bottom]` in PDF points (1/72 inch) measured from the top-left corner of the page; an A4 page is about 595 × 842.

### Top level

| Key | Meaning | Example |
|---|---|---|
| `schema_version` | Version of this JSON layout. Changes only if keys are added, renamed or removed. | `"1.1"` |
| `parser_version` | Version of the extraction rules that produced the file. | `"1.3.0"` |

### `document`

| Key | Meaning | Example |
|---|---|---|
| `filename` | Name of the uploaded file. | `"Table 03_Ver.01.pdf"` |
| `sha256` | Fingerprint of the file bytes; identifies exactly which file was read. | `"f0599330…2cd2e60"` |
| `page_count` | Number of pages read. | `20` |
| `table_number` | AIS table number from the title "Table 3 of AIS 007". `null` if there is no such title. | `"3"`, `"4E"` |
| `standard` | Standard named in that title. | `"AIS-007"` |
| `part` | Part letter from "PART B – VEHICLE OVERALL". | `"B"` |
| `title` | Part title, or the complete form heading when no part title is printed. | `"VEHICLE OVERALL"`; Table 11's two-line heading |
| `document_date` | Date printed as "Date: …" on page 1, as written. | `"06.08.2026"` |

### `extraction`

| Key | Meaning | Example |
|---|---|---|
| `method` | How the content was read. Always native text and ruled tables (no OCR). | `"native_text_and_ruled_tables"` |
| `generated_at` | When the file was produced (UTC). | `"2026-09-30T15:24:08+00:00"` |
| `status` | `"complete"` when there are no warnings, otherwise `"needs_review"`. | Table 03 is `"needs_review"` because pages 1, 3 and 16 contain images |
| `field_count` | Number of records in `fields`. | `646` |
| `table_count` | Number of tables found on all pages, including signature-block tables. | `38` |
| `requires_ocr_pages` | Pages with almost no selectable text (scanned images). | `[]`; a scanned page 4 would give `[4]` |
| `warnings` | Every page warning, with its page number. | `{"source_page": 1, "message": "Embedded images are referenced by location; their visual content is not transcribed."}` |

### `fields[]`: one record per form row

| Key | Meaning | Example |
|---|---|---|
| `id` | Unique record id within this file. Use it for links. | `"f00002"` |
| `field_id` | Clause number as printed, without spaces or a trailing dot. `null` on forms without numbers (Table 07, Table 11). Can repeat if the form repeats it. | `"B1.1"`; printed `"D 22.14.4 I."` becomes `"D22.14.4"` |
| `parent_id` | `id` of the parent record, found from the clause number. `null` at the top level. | B1.1 → the record of B1.0; A1.1 → A1.0 |
| `level` | Depth in the hierarchy (1 = top). | B1.0 is `1`, B1.1 is `2`, B1.8.1 is `3` |
| `kind` | `"section"` for a heading (number ends in `.0`, or no value is filled in); otherwise `"field"`. | A1.0 "Details of Vehicle Manufacturer" is a section; A1.7 "Plant/(s) of manufacture" is a section because its value cell is empty |
| `description` | Text of the description cell, line breaks kept. | `"Overall Length mm"` |
| `source_page` | Page of the row. | `1` |
| `table_id` | Table the row belongs to (see `pages[].tables[].id`). `null` for text-only records. | `"p1-t1"` (page 1, table 1) |
| `row` | Row number in that table; `null` for a caption outside the table or a text-only record. | `2` |
| `bbox` | Box around the whole row. | `[19.08, 98.22, 579.18, 132.66]` |
| `values` | The declared values, in printed order (left to right, then top to bottom). Empty list when the row has no value cells. | B1.1 has six values (three body types × two wheelbases) |
| `continuation_rows` | Rows under this record that have no clause number of their own, with their cell texts. Nothing is dropped. | Table 4E 1.2.1.13.1 "Engine Power Table": `{"row": 30, "cells": ["(1)", "1100", "15.5"]}` |
| `references` | Mentions of annexures, enclosures or appendices in the description or values, as printed. | `["Refer Annexure T7 – C"]` on B1.8 |

### `fields[].values[]`

| Key | Meaning | Example |
|---|---|---|
| `text` | Value exactly as printed: units, placeholders and line breaks kept, no number conversion. `""` means the cell is empty. | `"4750"`, `"10 degs"`, `"NA"`, `"--"`, `"Diesel\n(Maximum 7% bio-diesel blend)"` |
| `column_label` | Column heading the value sits under, when the section has a heading row. | `"2490 WB"`, `"GVW 2890 kg"`, `"2026"` in Table 11 |
| `row_label` | Row heading inside the field, or the row heading of a year grid. | `"CC"`, `"FSD"`, `"HSD"`, `"FSD / HSD"`, `"JAN"`, `"CODE"` |
| `source_page` | Page of the value. | `1` |
| `bbox` | Box of the cell the value was read from. | `[269.0, 109.68, 421.72, 132.66]` |
| `inherited_from_merged_cell` | `true` when the value comes from a merged cell that started in an earlier row and also covers this one. | B1.1 HSD → 4925 is `true`: the 4925 cell is printed once across the FSD and HSD rows |
| `source_cell` | The table cell the value was read from: `table_id`, `row`, `column`. For inherited values it points to the row that owns the merged cell. | HSD's 4925 → `{"table_id": "p1-t1", "row": 3, "column": 4}` (row 3 is FSD) |

### `pages[]`

| Key | Meaning | Example |
|---|---|---|
| `page_number` | Page number. | `1` |
| `width`, `height` | Page size in points. | `595.44`, `841.68` (A4) |
| `raw_text` | All selectable text on the page, in reading order. Useful when a table could not be interpreted. | |
| `text_outside_tables` | Each printed line that is not inside a table cell, with its box. Together with the table cells, every printed character has exactly one position. | `{"text": "Code for Year of Production: (for 30 years): Digit 10 in VIN", "bbox": [90.0, 45.33, 308.006, 54.33]}` (Table 11 page 2) |
| `requires_ocr` | `true` when the page has fewer than 40 characters of text (likely a scan). | `false` |
| `warnings` | Notes for this page. | Image present; no ruled table detected; OCR required |
| `tables` | Every table found on the page (below). | Table 03 page 1 has a content table and a signature table |
| `images` | Location of each embedded picture. The picture content is not read. | `{"id": "p1-image1", "bbox": [186.75, 18.0, 393.3, 52.2], "transcribed": false}` (the logo) |

### `pages[].tables[]`

| Key | Meaning | Example |
|---|---|---|
| `id` | Table id: page and position. | `"p1-t1"` |
| `source_page` | Page of the table. | `1` |
| `bbox` | Box around the table. | `[19.08, 64.26, 579.18, 737.5]` |
| `role` | `"content"`, or `"footer"` for the signature block (Manufacturer / Test agency), which is kept but not turned into fields. | `"footer"` |
| `parent` | For a table printed inside another table's cell: that table and cell. Otherwise `null`. | Table 03 page 7: `{"table_id": "p7-t1", "row": 20, "column": 2}` |
| `rows` | The grid as a list of rows. `null` marks a position covered by a merged cell, or a blank area with no printed cell (the cells' spans tell them apart); `""` is a real empty cell. | `["B1.1", "Overall Length mm", null, "CC", "4750", "4988", null]` |
| `row_count`, `column_count` | Grid size, from every printed border line. Word-made PDFs often have extra thin columns. | `50`, `7` |
| `cells` | Each real cell once, with its position, size and text (below). | |

### `pages[].tables[].cells[]`

| Key | Meaning | Example |
|---|---|---|
| `row`, `column` | Top-left grid position of the cell. | `3`, `4` |
| `row_span`, `column_span` | How many grid rows and columns the cell covers. Above 1 means a merged cell. | 4925 on Table 03 has `row_span: 2` (FSD and HSD rows) |
| `text` | Cell text as printed. | `"4925"` |
| `bbox` | Box of the cell. | `[269.0, 109.68, 421.72, 132.66]` |
| `ruled` | `false` when the PDF leaves part of this cell's border unprinted; the box is then bounded by the nearest printed lines. | Table 06 page 8 `E 22.4` |

### What is not in the output

- Content of images and drawings (only their position is recorded).
- Text of scanned pages (the page is flagged instead).
- Numbers converted from text, or units split off: `"170 Nm @ 1600 – 2400 rpm"` stays as written.
- Links between documents: `references` records "Refer Annexure T7 – C" as text but does not open Table 07.

## Development PDFs and validation checks

All seven supplied PDFs are available for development and regression checks. There is no reserved validation or holdout split. Place all originals in `pdfs/development/` as listed in [dataset_manifest.json](dataset_manifest.json); their hashes verify that the files are unchanged. Client PDFs are not stored in this repository.

| Set | Documents | Pages | Purpose |
|---|---|---:|---|
| `pdfs/development/` | Tables 02, 03, 05, 06, 07, 11, 4E | 64 | Parser development and checks on all supplied layouts |

Tables 06 and 11 were moved from the former holdout folder without changing their bytes. The v1.0 freeze metadata and [HOLDOUT_REPORT.md](evaluation/HOLDOUT_REPORT.md) remain historical records; their former development restriction no longer applies. Existing annotations from that run remain useful regression expectations.

### Primary check: printed content and structure

Validate text preservation, page/table/cell order, row and column spans, blank cells, nested tables, and the information needed to reconstruct the source PDF:

```powershell
.\.venv\Scripts\python.exe audit_structure.py
```

This checks every supplied PDF and writes `output/validation/structure_report.md` and `structure_report.json`. Here `validation` names the output reports, not a separate source-document split. Interpretation issues are reported separately from preservation failures.

With v1.3.0 all 64 pages pass: page text and order are preserved, cell spans are consistent, and every printed character is stored in exactly one table cell or `text_outside_tables` line. The JSON is aimed at rebuilding the content and table structure. It does not store fonts, exact glyph positions, image bytes or border drawings, so it cannot produce a pixel-identical copy.

### Sampled value and interpretation regressions

To run the existing 74 sampled value checks and two variant-label checks on Tables 06 and 11:

```powershell
.\.venv\Scripts\python.exe evaluate.py
```

`--regression` remains an accepted alias. Current extracted JSON is written to `output/regression/`, and results are saved in [REGRESSION_REPORT.md](evaluation/REGRESSION_REPORT.md). This command uses the active parser and never overwrites the historical holdout report.

v1.3.0 passes these sampled checks. They do not establish complete structural fidelity. All 390 Table 11 code mappings and its nine ordinary fields are checked separately in `tests/test_table11.py`; the all-PDF structure audit remains the primary preservation check.

## Automated checks

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

All test PDF fixtures now use `pdfs/development/`. `tests/test_v1_1.py` pins the v1.1 behaviour and `tests/test_table11.py` checks Table 11's full code mappings. The suite covers known values, merged rows, shared cells, parent/source links, upload validation, encrypted/corrupt PDFs, preview rendering, JSON/ZIP downloads, duplicate filenames, partial batch failure, expiration, and clearing a batch.

## Application files and API

- `app.py`: local FastAPI server, temporary upload storage, queue, downloads, and source page rendering.
- `extractor/engine.py`: deterministic extraction engine (parser version 1.3.0).
- `static/`: responsive upload/review interface with Fields, Tables, JSON, and Text views.
- `audit_structure.py`: all-PDF content/order/layout audit, with interpretation notes reported separately.
- `visual_proof.py`: draws structural problems found in the JSON on the PDF page (`output/validation/proof/`).
- `evaluate.py` and `evaluation/`: sampled development regressions and preserved historical reports.

API documentation is available at http://localhost:8000/docs. Upload with multipart `files` to `POST /api/jobs`; poll `GET /api/jobs/{id}`; retrieve results from `GET /api/jobs/{id}/documents/{doc_id}`. Downloads use `/download` on the job or document URL.

Limits: 25 MB per PDF, 100 MB per batch, 200 pages per document, and 12 retained/active batches. Extraction is queued through one worker. Temporary uploads/results expire after one hour of inactivity (cleanup occurs on API access); previous-process temporary files are cleared on restart. **New batch** immediately removes the current finished batch's temporary files. Downloaded JSON and the supplied source PDFs are separate from this temporary storage.
