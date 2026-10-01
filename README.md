# Jags AL Data Extracter

A small local application for uploading technical specification PDFs, reviewing extracted content beside the source pages, and downloading JSON. It supports batches of up to 10 PDFs, individual JSON downloads, and a batch ZIP.

## Run on Windows

Python 3.11 or newer is required. From this folder:

```powershell
.\start.ps1 -Install
```

After the first installation, run `.\start.ps1`. Open **http://localhost:8000**. If PowerShell blocks scripts, use the equivalent commands:

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

### Known issues from the holdout

Some multi-column layouts include a narrow blank spacer cell in the field values. Some category/heater/AC headers are present in raw tables but are not assigned as `column_label` values. Review the Tables view when interpreting variants. The [holdout report](evaluation/HOLDOUT_REPORT.md) identifies the measured failures. These cases were left in the frozen version instead of tuning against the reserved test set.

The extraction uses the earlier project's idea of deterministic clause regexes and parent relationships, adapted for these AIS forms. The new schema and CPU-only extraction are independent of the original GPU/OCR and AI labeling services. Reference reviewed: [PaddleOCR-Reggex-Experiment](https://github.com/sriram403/PaddleOCR-Reggex-Experiment), commit `10276a86fe7c29b34f245622eb63af686e1734ff`. A read-only clone is in `reference/`.

## JSON structure

Top-level keys are `schema_version`, `parser_version`, `document`, `extraction`, `fields`, and `pages`. A field looks like this (abbreviated):

```json
{
  "id": "f00007",
  "field_id": "A1.6",
  "parent_id": "f00001",
  "kind": "field",
  "description": "Name of model and variants\n(Features differentiating the model and its variants to\nbe given in a separate table)",
  "values": [
    {
      "text": "BADA DOST i9 TNZX",
      "column_label": null,
      "row_label": null,
      "source_page": 1,
      "inherited_from_merged_cell": false,
      "source_cell": {"table_id": "p1-t1", "row": 7, "column": 3}
    }
  ],
  "source_page": 1
}
```

`id` uniquely identifies a record within its document. `field_id` reflects what was printed and can repeat or be null. Parent links use record `id` values. Page numbers are one-based; cell row/column indices are zero-based. Coordinates are PDF points from the top-left of the page. Table `rows` keep `null` for positions covered by merged cells, while `cells` describes the actual cell owners and spans. No numeric conversion or cross-document conflict resolution is attempted.

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

## Automated checks

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

The checks use development documents only. They cover known values, merged rows, shared cells, parent/source links, upload validation, encrypted/corrupt PDFs, preview rendering, JSON/ZIP downloads, duplicate filenames, partial batch failure, expiration, and clearing a batch.

## Application files and API

- `app.py`: local FastAPI server, temporary upload storage, queue, downloads, and source page rendering.
- `extractor/engine.py`: frozen deterministic extraction engine.
- `static/`: responsive upload/review interface with Fields, Tables, JSON, and Text views.
- `evaluate.py` and `evaluation/`: reproducible sampled holdout assessment.

API documentation is available at http://localhost:8000/docs. Upload with multipart `files` to `POST /api/jobs`; poll `GET /api/jobs/{id}`; retrieve results from `GET /api/jobs/{id}/documents/{doc_id}`. Downloads use `/download` on the job or document URL.

Limits: 25 MB per PDF, 100 MB per batch, 200 pages per document, and 12 retained/active batches. Extraction is queued through one worker. Temporary uploads/results expire after one hour of inactivity (cleanup occurs on API access); previous-process temporary files are cleared on restart. **New batch** immediately removes the current finished batch's temporary files. Downloaded JSON and the supplied source PDFs are separate from this temporary storage.
