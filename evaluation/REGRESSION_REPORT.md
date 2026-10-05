# Development regression checks

Parser: `1.3.0`. The original v1.0 result is preserved in [HOLDOUT_REPORT.md](HOLDOUT_REPORT.md).

All seven supplied PDFs are available for development. This report reuses the sampled expectations for Tables 06 and 11.

Processed **14/14 pages** across two development PDFs.

Sampled field-value/table-cell checks: **74/74 (100.0%)**.

Variant label checks: **2/2**.

This percentage describes only the manually annotated sample; it is not a whole-document accuracy estimate.

Expected values transcribed from original PDF text and rendered source pages before running the frozen extractor on holdout. Whitespace is normalized; spelling, case, punctuation, units, value order, and placeholders must match.

All seven supplied PDFs are development fixtures. These sampled checks cover Tables 06 and 11 only; they do not establish complete row/column or layout fidelity. Run audit_structure.py for structural preservation checks across all seven PDFs. Interpretation labels are reported separately.

| Document | Pages | Extracted fields | Tables | Passed value checks |
|---|---:|---:|---:|---:|
| Table 06_Ver.01.pdf | 12 | 435 | 21 | 58/58 |
| Table 11_Ver.01.pdf | 2 | 38 | 5 | 16/16 |

## Items needing review

No failures in the sampled checks.

The original page text, table cells, and cell positions remain available in JSON for manual review. Diagrams and embedded image content are not transcribed. Variant labels are inferred conservatively and are incomplete for layouts outside the development set.

To repeat this run: `.\.venv\Scripts\python.exe evaluate.py` (`--regression` is also accepted).

The primary all-PDF structure check is `.\.venv\Scripts\python.exe audit_structure.py`; its findings are separate from field interpretation.
