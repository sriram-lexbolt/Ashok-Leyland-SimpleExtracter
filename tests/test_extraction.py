from pathlib import Path
import pytest
from pypdf import PdfWriter

from extractor.engine import ExtractionError, extract_pdf, field_code

ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT = ROOT / "pdfs" / "development"


@pytest.fixture(scope="module")
def general():
    return extract_pdf(DEVELOPMENT / "Table 02_Ver.01.pdf")


@pytest.fixture(scope="module")
def dimensions():
    return extract_pdf(DEVELOPMENT / "Table 03_Ver.01.pdf")


def get_field(result, code):
    return next(f for f in result["fields"] if f["field_id"] == code)


def texts(field):
    return [v["text"] for v in field["values"]]


@pytest.mark.parametrize("code,values", [
    ("A1.1", ["Ashok Leyland Limited No.1, Sardar Patel Road, Guindy, Chennai 600 032"]),
    ("A1.4", ["XXXXXXXX@ashokleyland.com"]),
    ("A1.6", ["BADA DOST i9 TNZX"]),
    ("A1.6.1", ["Diesel\n(Maximum 7% bio-diesel blend)"]),
    ("A1.8", ["NA"]), ("A1.8.1", ["--"]),
    ("A2.1.3", ["4x2"]), ("A2.2", ["N1"]),
    ("A3.1", ["10 degs", "8.5 degs"]),
])
def test_manually_checked_development_values(general, code, values):
    assert texts(get_field(general, code)) == values


def test_merged_variants_and_subrows(dimensions):
    field = get_field(dimensions, "B1.1")
    assert [(v["row_label"], v["column_label"], v["text"]) for v in field["values"]] == [
        ("CC", "2490 WB", "4750"), ("CC", "2640 WB", "4988"),
        ("FSD", "2490 WB", "4925"), ("FSD", "2640 WB", "5225"),
        ("HSD", "2490 WB", "4925"), ("HSD", "2640 WB", "5225")]
    assert all(v["inherited_from_merged_cell"] for v in field["values"][-2:])


def test_shared_value_does_not_become_blank(dimensions):
    assert "Refer Annexure T7" in texts(get_field(dimensions, "B1.8.1"))[0]


def test_hierarchy_and_footer(general):
    assert get_field(general, "A1.6.1")["parent_id"] == get_field(general, "A1.6")["id"]
    assert get_field(general, "A1.1")["parent_id"] == get_field(general, "A1.0")["id"]
    assert len(general["fields"]) == 31
    assert general["pages"][0]["tables"][-1]["role"] == "footer"
    assert "Date: 06.08.2026" in general["pages"][0]["raw_text"]
    assert [v["column_label"] for v in get_field(general, "A3.1")["values"]] == ["GVW 2890 kg", "GVW 3390 kg"]
    assert all(v["column_label"] is None for v in get_field(general, "A3.0")["values"])


def test_values_point_to_real_cells(dimensions):
    tables = {t["id"]: t for p in dimensions["pages"] for t in p["tables"]}
    for f in dimensions["fields"]:
        for v in f["values"]:
            source = v["source_cell"]
            cell = next(c for c in tables[source["table_id"]]["cells"]
                        if c["row"] == source["row"] and c["column"] == source["column"])
            assert cell["text"] == v["text"]
            assert v["bbox"] == cell["bbox"]
    assert all(f["parent_id"] is None or f["parent_id"] in {x["id"] for x in dimensions["fields"]} for f in dimensions["fields"])


def test_normalize_printed_clause_ids():
    assert field_code("D 22.14.4 I.") == "D22.14.4"
    assert field_code("B 2.3.4") == "B2.3.4"
    assert field_code("1.2.1.") == "1.2.1"
    assert field_code("4x2") is None


def test_no_text_is_flagged(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    path = tmp_path / "blank.pdf"
    writer.write(path)
    result = extract_pdf(path)
    assert result["extraction"]["requires_ocr_pages"] == [1]
    assert result["extraction"]["status"] == "needs_review"
    assert result["fields"] == []


def test_encrypted_and_corrupt_documents(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.encrypt("private-password")
    path = tmp_path / "encrypted.pdf"
    writer.write(path)
    with pytest.raises(ExtractionError):
        extract_pdf(path)
    path.write_bytes(b"%PDF-broken")
    with pytest.raises(ExtractionError):
        extract_pdf(path)
