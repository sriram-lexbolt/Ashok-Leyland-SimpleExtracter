"""Independent sampled holdout evaluation; never tune the engine in this script.

Without arguments: reproduces the frozen v1.0 holdout result and refuses to run if engine.py changed.
With --regression: re-checks the same documents with a newer parser. Those documents have been
examined since the v1.0 result, so a regression run is not an unseen-accuracy claim.
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


def evaluate(regression=False):
    frozen = json.loads((ROOT / "evaluation/frozen_parser.json").read_text(encoding="utf-8"))
    engine_hash = hashlib.sha256((ROOT / "extractor/engine.py").read_bytes()).hexdigest()
    if not regression and frozen["engine_sha256"] != engine_hash:
        raise RuntimeError("The parser changed after the holdout freeze. Preserve the original report and use a NEW unseen test set for a new accuracy claim.")
    expected_path = ROOT / "evaluation/holdout_expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "dataset_manifest.json").read_text(encoding="utf-8"))
    hashes = {Path(d["path"]).name: d["sha256"] for d in manifest["holdout"]}
    output = ROOT / ("output/regression" if regression else "output/holdout")
    output.mkdir(parents=True, exist_ok=True)
    report = {"mode": "regression" if regression else "holdout", "parser_version": PARSER_VERSION,
              "engine_sha256": engine_hash, "frozen_parser": frozen, "ground_truth_sha256": hashlib.sha256(expected_path.read_bytes()).hexdigest(),
              "method": expected["method"], "limitations": expected["limitations"], "documents": []}
    for doc in expected["documents"]:
        path = ROOT / "pdfs/holdout" / doc["filename"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[doc["filename"]]:
            raise RuntimeError(f"Holdout PDF changed: {doc['filename']}")
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
    report_path = ROOT / f"evaluation/{'regression' if regression else 'holdout'}_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_markdown(report)
    print(json.dumps(report["summary"], indent=2))
    for d in report["documents"]:
        for check in d["checks"]:
            if not check["passed"]:
                print("FAILED:", d["filename"], json.dumps(check, ensure_ascii=False))


def write_markdown(report):
    s = report["summary"]
    regression = report.get("mode") == "regression"
    if regression:
        lines = ["# Regression check on the former holdout", "",
                 f"Parser: `{report['parser_version']}`. The original v1.0 result is in [HOLDOUT_REPORT.md](HOLDOUT_REPORT.md).", "",
                 "**These two documents were examined while fixing the v1.0 failures, so this is a regression check, not unseen accuracy.** "
                 "A new accuracy claim needs PDFs that were not used to build this version.", ""]
    else:
        lines = ["# Holdout evaluation", "", f"Frozen parser: `{report['frozen_parser']['parser_version']}`.", ""]
    lines += [f"Processed **{s['pages_processed']}/{s['expected_pages']} pages** across two reserved PDFs.", "",
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
              f"To repeat this run: `.\\.venv\\Scripts\\python.exe evaluate.py{' --regression' if regression else ''}`.", "",
              "Do not tune against these held-out documents and then report a new result as unseen accuracy. Reserve new PDFs for the next parser version."]
    (ROOT / f"evaluation/{'REGRESSION' if regression else 'HOLDOUT'}_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    evaluate(regression="--regression" in sys.argv[1:])
