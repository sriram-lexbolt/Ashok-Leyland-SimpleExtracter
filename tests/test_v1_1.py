"""Checks for the v1.1 parser changes.

Development documents pin the new behaviour. The Table 06 / Table 11 checks are regression
tests: those documents were the v1.0 holdout and were examined while fixing these cases.
"""
from pathlib import Path
import pytest

from extractor.engine import extract_pdf

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "pdfs" / "development"
HOLDOUT = ROOT / "pdfs" / "holdout"


@pytest.fixture(scope="module")
def dimensions():
    return extract_pdf(DEV / "Table 03_Ver.01.pdf")


@pytest.fixture(scope="module")
def brakes():
    return extract_pdf(DEV / "Table 05_Ver.01.pdf")


@pytest.fixture(scope="module")
def summary():
    return extract_pdf(DEV / "Table 07_Ver.01.pdf")


@pytest.fixture(scope="module")
def electrical():
    return extract_pdf(HOLDOUT / "Table 06_Ver.01.pdf")


@pytest.fixture(scope="module")
def vin_codes():
    return extract_pdf(HOLDOUT / "Table 11_Ver.01.pdf")


def get_field(result, code):
    return next(f for f in result["fields"] if f["field_id"] == code)


def labels(field):
    return [v["column_label"] for v in field["values"]]


def test_signature_box_without_manufacturer_is_footer(summary):
    assert not any(f["description"].startswith(("Document No", "Page 1 of 6")) for f in summary["fields"])
    assert summary["pages"][0]["tables"][-1]["role"] == "footer"


def test_uncoded_sections_are_siblings(summary):
    sections = {f["description"]: f for f in summary["fields"] if f["kind"] == "section" and f["source_page"] == 1}
    assert sections["Engine"]["parent_id"] == sections["Vehicle data"]["parent_id"]
    assert sections["Clutch"]["level"] == sections["Engine"]["level"]
    assert max(f["level"] for f in summary["fields"]) <= 3


def test_heading_row_labels_its_clause_family(brakes):
    assert labels(get_field(brakes, "D7.5.2")) == ["Description", "Capacity"]
    assert "Description" not in labels(get_field(brakes, "D7.6.1"))


def test_heading_field_labels_its_sub_clauses(dimensions):
    assert labels(get_field(dimensions, "B3.1.1")) == ["APOLLO", "CEAT", "APOLLO", "CEAT"]
    assert labels(get_field(dimensions, "B1.1")) == ["2490 WB", "2640 WB"] * 3


def test_values_are_not_taken_as_headings(dimensions):
    # "10.0 m | 10.9 m" are measurements and "NA | Yes" are answers, not column headings.
    assert all(label is None for label in labels(get_field(dimensions, "B8.11")))
    assert all(label is None for label in labels(get_field(dimensions, "B13.2")))


def test_references_ignore_plain_words(dimensions):
    assert get_field(dimensions, "B8.4")["references"] == []
    assert get_field(dimensions, "B1.8")["references"] == ["Refer Annexure T7 – C"]


def test_regression_blank_spacer_is_not_a_value(electrical, vin_codes):
    assert [v["text"] for v in get_field(electrical, "E28.4")["values"]] == ["NA", "NA", "4 kW"]
    assert [v["text"] for v in get_field(electrical, "E29.4")["values"]] == ["4", "4", "4"]
    year_codes = next(f for f in vin_codes["fields"] if f["description"] == "CODE")
    assert "" not in [v["text"] for v in year_codes["values"]] and len(year_codes["values"]) == 15


def test_regression_variant_labels(electrical):
    assert labels(get_field(electrical, "E28.4")) == ["Blower", "Low-Cost Heater", "AC"]
    assert labels(get_field(electrical, "E15.3.2")) == ["Provided Category - 5", "Provided Category - 6"]
