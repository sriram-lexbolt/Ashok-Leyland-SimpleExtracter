# Regression check on the former holdout

Parser: `1.1.0`. The original v1.0 result is in [HOLDOUT_REPORT.md](HOLDOUT_REPORT.md).

**These two documents were examined while fixing the v1.0 failures, so this is a regression check, not unseen accuracy.** A new accuracy claim needs PDFs that were not used to build this version.

Processed **14/14 pages** across two reserved PDFs.

Sampled field-value/table-cell checks: **74/74 (100.0%)**.

Variant label checks: **2/2**.

This percentage describes only the manually annotated sample; it is not a whole-document accuracy estimate.

Expected values transcribed from original PDF text and rendered source pages before running the frozen extractor on holdout. Whitespace is normalized; spelling, case, punctuation, units, value order, and placeholders must match.

This is a purposive sample of field values and table cells, not a complete annotation of every field. First pages had been inspected during pre-split triage. No parser tuning used these documents after the split. Variant-label checks are reported separately.

| Document | Pages | Extracted fields | Tables | Passed value checks |
|---|---:|---:|---:|---:|
| Table 06_Ver.01.pdf | 12 | 433 | 21 | 58/58 |
| Table 11_Ver.01.pdf | 2 | 40 | 5 | 16/16 |

## Items needing review

No failures in the sampled checks.

The original page text, table cells, and cell positions remain available in JSON for manual review. Diagrams and embedded image content are not transcribed. Variant labels are inferred conservatively and are incomplete for layouts outside the development set.

To repeat this evaluation without changing the frozen parser: `.\.venv\Scripts\python.exe evaluate.py`.

Do not tune against these held-out documents and then report a new result as unseen accuracy. Reserve new PDFs for the next parser version.
