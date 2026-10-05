"""Sampled development regression checks on Tables 06 and 11.

All supplied PDFs are now available for development. The original v1.0 holdout
report remains historical; this script never overwrites it. --regression is a
compatible alias for the default run. Use audit_structure.py for all-PDF layout checks.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

from extractor.engine import PARSER_VERSION, extract_pdf

ROOT = Path(__file__).resolve().parent


def normalized(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(value or ""))).strip()


def find_field(result, spec):
    matches = [f for f in result["fields"] if f["source_page"] == spec["page"]
               and ("field_id" not in spec or f["field_id"] == spec["field_id"])
               and ("description_contains" not in spec or normalized(spec["description_contains"]) in normalized(f["description"]))]
    index = spec.get("occurrence", 1) - 1
    return matches[index] if index < len(matches) else None


def table_cell(result, spec):
    tables = [t for t in result["pages"][spec["page"] - 1]["tables"]
              if any(normalized(spec["table_contains"]) in normalized(c["text"]) for c in t["cells"])]
    rows = []
    for table in tables:
        for r in range(table["row_count"]):
            cells = sorted([c for c in table["cells"] if c["row"] == r and c["text"]], key=lambda c: c["bbox"][0])
            if cells and normalized(cells[0]["text"]) == normalized(spec["row_label"]):
                rows.append(cells)
    occurrence = spec.get("occurrence", 1) - 1
    if occurrence >= len(rows) or spec["value_index"] >= len(rows[occurrence]):
        return None
    return rows[occurrence][spec["value_index"]]["text"]


def evaluate():
    frozen = json.loads((ROOT / "evaluation/frozen_parser.json").read_text(encoding="utf-8"))
    engine_hash = hashlib.sha256((ROOT / "extractor/engine.py").read_bytes()).hexdigest()
    expected_path = ROOT / "evaluation/holdout_expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "dataset_manifest.json").read_text(encoding="utf-8"))
    fixtures = {Path(d["path"]).name: d for d in manifest["development"]}
    output = ROOT / "output/regression"
    output.mkdir(parents=True, exist_ok=True)
    report = {"mode": "regression", "dataset_role": "development", "parser_version": PARSER_VERSION,
              "engine_sha256": engine_hash, "frozen_parser": frozen, "ground_truth_sha256": hashlib.sha256(expected_path.read_bytes()).hexdigest(),
              "method": expected["method"],
              "annotation_provenance_limitations": expected["limitations"],
              "limitations": "All seven supplied PDFs are development fixtures. These sampled checks cover Tables 06 and 11 only; they do not establish complete row/column or layout fidelity. Run audit_structure.py for structural preservation checks across all seven PDFs. Interpretation labels are reported separately.",
              "documents": []}
    for doc in expected["documents"]:
        fixture = fixtures[doc["filename"]]
        path = ROOT / fixture["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != fixture["sha256"]:
            raise RuntimeError(f"Development PDF changed: {doc['filename']}")
        result = extract_pdf(path)
        (output / (path.stem + ".json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        checks = []
        for spec in doc["checks"]:
            if spec.get("type") == "table_cell":
                actual = table_cell(result, spec)
                passed = actual is not None and normalized(actual) == normalized(spec["expected"])
            else:
                field = find_field(result, spec)
                actual = [v["text"] for v in field["values"]] if field else None
                passed = field is not None and (all(not normalized(v) for v in actual) if spec.get("empty_value") else
                                               [normalized(v) for v in actual] == [normalized(v) for v in spec["values"]])
            checks.append({"expected": spec, "actual": actual, "passed": passed})
        label_checks = []
        for spec in doc["variant_label_checks"]:
            field = find_field(result, spec)
            actual = [v["column_label"] for v in field["values"]] if field else None
            label_checks.append({"expected": spec, "actual": actual,
                                 "passed": actual is not None and [normalized(v) for v in actual] == [normalized(v) for v in spec["labels"]]})
        report["documents"].append({"filename": doc["filename"], "sha256": result["document"]["sha256"],
                                    "expected_pages": doc["page_count"], "processed_pages": len(result["pages"]),
                                    "field_count": len(result["fields"]), "table_count": result["extraction"]["table_count"],
                                    "checks": checks, "variant_label_checks": label_checks,
                                    "review_notes": result["extraction"]["warnings"]})
    checks = [c for d in report["documents"] for c in d["checks"]]
    labels = [c for d in report["documents"] for c in d["variant_label_checks"]]
    report["summary"] = {"value_checks_passed": sum(c["passed"] for c in checks), "value_checks_total": len(checks),
                         "sampled_value_accuracy_percent": round(100 * sum(c["passed"] for c in checks) / len(checks), 2),
                         "variant_label_checks_passed": sum(c["passed"] for c in labels), "variant_label_checks_total": len(labels),
                         "pages_processed": sum(d["processed_pages"] for d in report["documents"]),
                         "expected_pages": sum(d["expected_pages"] for d in report["documents"])}
    report_path = ROOT / "evaluation/regression_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    write_markdown(report)
    print(json.dumps(report["summary"], indent=2))
    for d in report["documents"]:
        for check in d["checks"]:
            if not check["passed"]:
                print("FAILED:", d["filename"], json.dumps(check, ensure_ascii=False))


def write_markdown(report):
    s = report["summary"]
    lines = ["# Development regression checks", "",
             f"Parser: `{report['parser_version']}`. The original v1.0 result is preserved in [HOLDOUT_REPORT.md](HOLDOUT_REPORT.md).", "",
             "All seven supplied PDFs are available for development. This report reuses the sampled expectations for Tables 06 and 11.", ""]
    lines += [f"Processed **{s['pages_processed']}/{s['expected_pages']} pages** across two development PDFs.", "",
             f"Sampled field-value/table-cell checks: **{s['value_checks_passed']}/{s['value_checks_total']} ({s['sampled_value_accuracy_percent']}%)**.", "",
             f"Variant label checks: **{s['variant_label_checks_passed']}/{s['variant_label_checks_total']}**.", "",
             "This percentage describes only the manually annotated sample; it is not a whole-document accuracy estimate.", "",
             report["method"], "", report["limitations"], "",
             "| Document | Pages | Extracted fields | Tables | Passed value checks |", "|---|---:|---:|---:|---:|"]
    for d in report["documents"]:
        passed = sum(c["passed"] for c in d["checks"])
        lines.append(f"| {d['filename']} | {d['processed_pages']} | {d['field_count']} | {d['table_count']} | {passed}/{len(d['checks'])} |")
    lines += ["", "## Items needing review", ""]
    failures = []
    for d in report["documents"]:
        for c in d["checks"] + d["variant_label_checks"]:
            if not c["passed"]:
                spec = c["expected"]
                locator = spec.get("field_id") or spec.get("description_contains") or spec.get("row_label")
                expected = spec.get("values", spec.get("labels", spec.get("expected", "blank")))
                failures.append(f"- {d['filename']}, page {spec['page']}, {locator}: expected `{json.dumps(expected, ensure_ascii=False)}`; found `{json.dumps(c['actual'], ensure_ascii=False)}`.")
    lines.extend(failures or ["No failures in the sampled checks."])
    lines += ["", "The original page text, table cells, and cell positions remain available in JSON for manual review. Diagrams and embedded image content are not transcribed. Variant labels are inferred conservatively and are incomplete for layouts outside the development set.", "",
              "To repeat this run: `.\\.venv\\Scripts\\python.exe evaluate.py` (`--regression` is also accepted).", "",
              "The primary all-PDF structure check is `.\\.venv\\Scripts\\python.exe audit_structure.py`; its findings are separate from field interpretation."]
    (ROOT / "evaluation/REGRESSION_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if any(arg != "--regression" for arg in sys.argv[1:]):
        raise SystemExit("Usage: python evaluate.py [--regression]")
    evaluate()
