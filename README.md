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
- Text printed outside ruled tables is only in `raw_text`, except nearby captions of recognised year grids, which also become section records.
- Any embedded image, including a logo, sets the document status to `needs_review`.

Review the Tables view when interpreting variants.

The extraction uses the earlier project's idea of deterministic clause regexes and parent relationships, adapted for these AIS forms. The new schema and CPU-only extraction are independent of the original GPU/OCR and AI labeling services. Reference reviewed: [PaddleOCR-Reggex-Experiment](https://github.com/sriram403/PaddleOCR-Reggex-Experiment), commit `10276a86fe7c29b34f245622eb63af686e1734ff`. A read-only clone is in `reference/`.

## JSON output

Every PDF produces one JSON file with the same structure. The keys never change from PDF to PDF; only the number of items in lists and some values (which can be `null` when the PDF does not provide them) differ. Examples below are taken from the supplied Table 02, Table 03 and Table 4E files.

### Overview

```
{
  "schema_version": "1.0",
  "parser_version": "1.2.0",
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
      tables: [ { id, source_page, bbox, role, rows, row_count, column_count,
                  cells: [ { row, column, row_span, column_span, text, bbox } ] } ],
      images: [ { id, bbox, transcribed } ] }
  ]
}
```

`fields` is the interpreted view (one record per form row). `pages` is the evidence: the page text and every table cell as found, so any field can be checked against it.

Conventions: page numbers start at 1; table row and column numbers start at 0. A `bbox` is `[x0, top, x1, bottom]` in PDF points (1/72 inch) measured from the top-left corner of the page; an A4 page is about 595 × 842.

### Top level

| Key | Meaning | Example |
|---|---|---|
| `schema_version` | Version of this JSON layout. Changes only if keys are added, renamed or removed. | `"1.0"` |
| `parser_version` | Version of the extraction rules that produced the file. | `"1.2.0"` |

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
| `raw_text` | All selectable text on the page, in reading order. Useful when a table could not be interpreted. | Table 11 page 2 heading "Code for Year of Production: Digit 10 in VIN" is only here |
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
| `rows` | The grid as a list of rows. `null` marks a position covered by a merged cell; `""` is a real empty cell. | `["B1.1", "Overall Length mm", null, "CC", "4750", "4988", null]` |
| `row_count`, `column_count` | Grid size. Word-made PDFs often have extra thin columns. | `50`, `7` |
| `cells` | Each real cell once, with its position, size and text (below). | |

### `pages[].tables[].cells[]`

| Key | Meaning | Example |
|---|---|---|
| `row`, `column` | Top-left grid position of the cell. | `3`, `4` |
| `row_span`, `column_span` | How many grid rows and columns the cell covers. Above 1 means a merged cell. | 4925 on Table 03 has `row_span: 2` (FSD and HSD rows) |
| `text` | Cell text as printed. | `"4925"` |
| `bbox` | Box of the cell. | `[269.0, 109.68, 421.72, 132.66]` |

### What is not in the output

- Content of images and drawings (only their position is recorded).
- Text of scanned pages (the page is flagged instead).
- Numbers converted from text, or units split off: `"170 Nm @ 1600 – 2400 rpm"` stays as written.
- Links between documents: `references` records "Refer Annexure T7 – C" as text but does not open Table 07.

## Development and reserved test PDFs

The source PDFs are client documents and are not stored in this repository. To run the tests or the evaluation, place them in `pdfs/development/` and `pdfs/holdout/` as listed in [dataset_manifest.json](dataset_manifest.json); the recorded hashes confirm they are the original files.

The original PDFs were moved into two folders without changing their bytes. Hashes are recorded in [dataset_manifest.json](dataset_manifest.json).

| Set | Documents | Pages | Purpose |
|---|---:|---:|---|
| `pdfs/development/` | Tables 02, 03, 05, 07, 4E | 50 | Parser implementation and automated development checks |
| `pdfs/holdout/` | Tables 06, 11 | 14 | Evaluation after freezing the parser |

First pages were inspected for file triage before the split. After separation, the reserved PDFs were not used for parser tuning. The engine checksum and freeze timestamp are in `evaluation/frozen_parser.json`. Expected holdout values were transcribed from the originals before running extraction on that set.

The initial holdout run passed **72/74 sampled value/table-cell checks (97.3%)** and **0/2 variant-label checks**, processing **14/14 pages**. This is sample accuracy, not an estimate for every field or future PDF. Full details, expectations, and actual values are saved in `evaluation/holdout_report.json` and [HOLDOUT_REPORT.md](evaluation/HOLDOUT_REPORT.md).

Extracted JSON for the supplied files is under `output/development/` and `output/holdout/`. To reproduce the evaluation using the unchanged frozen parser:

```powershell
.\.venv\Scripts\python.exe evaluate.py
```

The evaluator refuses to run if the engine checksum has changed. A future parser should use a new unseen set for a new accuracy claim; these two documents can then become regression cases.

Parser v1.1.0 fixed the v1.0 holdout failures, so Tables 06 and 11 are now regression cases, not unseen data. Re-checking them with the current parser and the same expectations:

```powershell
.\.venv\Scripts\python.exe evaluate.py --regression
```

v1.2.0 passes 74/74 sampled value checks and 2/2 variant-label checks ([REGRESSION_REPORT.md](evaluation/REGRESSION_REPORT.md)). These original checks mostly inspect Table 11's raw grid cells; the complete code-to-year and code-to-month relationships are checked separately in `tests/test_table11.py`. Current JSON is written to `output/regression/`. This shows the fixes work on those cases; it is **not** an accuracy estimate for new documents. The v1.0 result above remains the last unseen measurement. A new accuracy claim needs PDFs that were not used to build the parser.

## Automated checks

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

`tests/test_v1_1.py` pins the v1.1 changes on development documents and includes regression checks on Tables 06 and 11. The other checks use development documents only. They cover known values, merged rows, shared cells, parent/source links, upload validation, encrypted/corrupt PDFs, preview rendering, JSON/ZIP downloads, duplicate filenames, partial batch failure, expiration, and clearing a batch.

## Application files and API

- `app.py`: local FastAPI server, temporary upload storage, queue, downloads, and source page rendering.
- `extractor/engine.py`: deterministic extraction engine (parser version 1.2.0).
- `static/`: responsive upload/review interface with Fields, Tables, JSON, and Text views.
- `evaluate.py` and `evaluation/`: reproducible sampled holdout assessment.

API documentation is available at http://localhost:8000/docs. Upload with multipart `files` to `POST /api/jobs`; poll `GET /api/jobs/{id}`; retrieve results from `GET /api/jobs/{id}/documents/{doc_id}`. Downloads use `/download` on the job or document URL.

Limits: 25 MB per PDF, 100 MB per batch, 200 pages per document, and 12 retained/active batches. Extraction is queued through one worker. Temporary uploads/results expire after one hour of inactivity (cleanup occurs on API access); previous-process temporary files are cleared on restart. **New batch** immediately removes the current finished batch's temporary files. Downloaded JSON and the supplied source PDFs are separate from this temporary storage.
