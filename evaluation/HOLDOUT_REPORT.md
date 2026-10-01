# Holdout evaluation

Frozen parser: `1.0.0`.

Processed **14/14 pages** across two reserved PDFs.

Sampled field-value/table-cell checks: **72/74 (97.3%)**.

Variant label checks: **0/2**.

This percentage describes only the manually annotated sample; it is not a whole-document accuracy estimate.

Expected values transcribed from original PDF text and rendered source pages before running the frozen extractor on holdout. Whitespace is normalized; spelling, case, punctuation, units, value order, and placeholders must match.

This is a purposive sample of field values and table cells, not a complete annotation of every field. First pages had been inspected during pre-split triage. No parser tuning used these documents after the split. Variant-label checks are reported separately.

| Document | Pages | Extracted fields | Tables | Passed value checks |
|---|---:|---:|---:|---:|
| Table 06_Ver.01.pdf | 12 | 433 | 21 | 56/58 |
| Table 11_Ver.01.pdf | 2 | 40 | 5 | 16/16 |

## Items needing review

- Table 06_Ver.01.pdf, page 9, E28.4: expected `["NA", "NA", "4 kW"]`; found `["NA", "", "NA", "4 kW"]`.
- Table 06_Ver.01.pdf, page 9, E29.4: expected `["4", "4", "4"]`; found `["4", "", "4", "4"]`.
- Table 06_Ver.01.pdf, page 4, E15.3.2: expected `["Provided Category - 5", "Provided Category - 6"]`; found `[null, null]`.
- Table 06_Ver.01.pdf, page 9, E28.4: expected `["Blower", "Low-Cost Heater", "AC"]`; found `[null, null, null, null]`.

The original page text, table cells, and cell positions remain available in JSON for manual review. Diagrams and embedded image content are not transcribed. Variant labels are inferred conservatively and are incomplete for layouts outside the development set.

To repeat this evaluation without changing the frozen parser: `.\.venv\Scripts\python.exe evaluate.py`.

Do not tune against these held-out documents and then report a new result as unseen accuracy. Reserve new PDFs for the next parser version.
