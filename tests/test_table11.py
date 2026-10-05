"""Full Table 11 code-grid regression, transcribed from both rendered year blocks.

These are reviewed regression cases, not an unseen accuracy measurement.
Unusual printed letters are intentional: never generate codes from a pattern.
"""
from collections import Counter
from pathlib import Path

import pytest

from extractor.engine import _interpret_table, extract_pdf

ROOT = Path(__file__).resolve().parents[1]
TITLE = ("DETAILS OF LOCATION OF CHASSIS NUMBER AND CODE FOR MONTH AND\n"
         "YEAR OF MANUFACTURE AS PER RULE 122 OF CMVR")
YEAR_TITLE = "Code for Year of Production: (for 30 years): Digit 10 in VIN"
MONTH_TITLE = "Code for Month of Production: (for 30 years): Digit 12 in VIN"
YEAR_CODES = {
    2026: "T V W X Y 1 2 3 4 5 6 7 8 9 A",
    2041: "B C D E F G H J K L M N P R S",
}
MONTH_CODES = {
    2026: {
        "JAN": "S T V W X Y 1 2 3 4 5 6 7 N 9",
        "FEB": "R S T V W X Y A B C D E F L W",
        "MAR": "P R S T V W X Y A B C D E K V",
        "APR": "N P R S T V W X Y A B C D J T",
        "MAY": "M N P R S T V W X Y A B C F S",
        "JUN": "L M N P R S T V W X Y A B D P",
        "JUL": "K L M N P R S T V W X Y A C N",
        "AUG": "J K L M N P R S T V W X Y B M",
        "SEP": "H J K L M N P R S T V W X Z L",
        "OCT": "G H J K L M N P R S T V W Y K",
        "NOV": "D G H J K L M N P R S T V W J",
        "DEC": "V W X Y 1 2 3 4 5 6 7 8 9 A B",
    },
    2041: {
        "JAN": "A B C D E F G H J K L M N P R",
        "FEB": "Y A B C D E F G H J K L M N P",
        "MAR": "X Y A B C D E F G H J K L M N",
        "APR": "W X Y A B C D E F G H J K L M",
        "MAY": "V W X Y A B C D E F G H J K L",
        "JUN": "T V W X Y A B C D E F G H J K",
        "JUL": "S T V W X Y A B C D E F G H J",
        "AUG": "R S T V W X Y A B C D E F G H",
        "SEP": "P R S T V W X Y A B C D E D G",
        "OCT": "N P R S T V W X Y A B C D C D",
        "NOV": "M N P R S T V W X Y A B C B C",
        "DEC": "C D E F G H J K L M N P R S T",
    },
}


@pytest.fixture(scope="module")
def vin():
    return extract_pdf(ROOT / "pdfs/development/Table 11_Ver.01.pdf")


def section(vin, title):
    matches = [f for f in vin["fields"] if f["description"] == title]
    assert len(matches) == 1
    return matches[0]


def grid_values(vin, title):
    parent = section(vin, title)
    return [v for f in vin["fields"] if f["parent_id"] == parent["id"] for v in f["values"]]


def test_all_thirty_year_codes(vin):
    actual = grid_values(vin, YEAR_TITLE)
    expected = [("CODE", str(start + offset), code)
                for start, codes in YEAR_CODES.items() for offset, code in enumerate(codes.split())]
    assert [(v["row_label"], v["column_label"], v["text"]) for v in actual] == expected


def test_all_three_hundred_sixty_month_codes(vin):
    actual = grid_values(vin, MONTH_TITLE)
    expected = [(month, str(start + offset), code)
                for start, months in MONTH_CODES.items() for month, codes in months.items()
                for offset, code in enumerate(codes.split())]
    assert [(v["row_label"], v["column_label"], v["text"]) for v in actual] == expected
    assert Counter((v["row_label"], v["column_label"]) for v in actual) == Counter(
        (month, str(year)) for month in MONTH_CODES[2026] for year in range(2026, 2056))


@pytest.mark.parametrize("description,expected", [
    ("Name of the Vehicle Manufacturer", ["Ashok Leyland Ltd,\n1, Sardar Patel Road, Guindy, Chennai – 600 032."]),
    ("Name of the basic model", ["BADA DOST i9 TNZX"]),
    ("Name of Variants", ["BADA DOST i8 TNZX"]),
    ("Place of Embossing", ["On LH frame between Bump Stop Mounting bracket and Rear Suspension Rear\nmounting bracket Assy. 500XYZVA5A"]),
    ("Place of PIN", ["NA"]),
    ("Place of Local information", ["NA"]),
    ("Height of the Chassis number", ["Min. 7 mm on Chassis frame;\nMin. 4 mm on Manufacturers plate"]),
    ("Example of Engine No", ["HJEZXYZ891"]),
    ("Example of Chassis No.", ["XYZABCGCD0JRDX737"]),
])
def test_all_ordinary_fields_keep_their_values_and_scope(vin, description, expected):
    field, = [f for f in vin["fields"] if f["description"].startswith(description)]
    assert [v["text"] for v in field["values"]] == expected
    assert all(v["column_label"] is None and v["row_label"] is None for v in field["values"])
    assert field["parent_id"] == section(vin, TITLE)["id"]


def test_headers_are_context_and_every_value_remains_traceable(vin):
    assert vin["document"]["title"] == TITLE
    assert vin["document"]["document_date"] == "18/8/2026"
    assert len(vin["fields"]) == 38
    assert not any(f["description"] in {"YEAR", "2026", "2041"} for f in vin["fields"])
    assert all(f["field_id"] is None for f in vin["fields"])
    tables = {t["id"]: t for p in vin["pages"] for t in p["tables"]}
    for title in (YEAR_TITLE, MONTH_TITLE):
        heading = section(vin, title)
        assert heading["row"] is None and heading["values"] == []
        assert heading["bbox"][3] <= tables[heading["table_id"]]["bbox"][1]
    for field in vin["fields"]:
        assert not field["table_id"] or tables[field["table_id"]]["role"] == "content"
        for value in field["values"]:
            source = value["source_cell"]
            cell, = [c for c in tables[source["table_id"]]["cells"]
                     if (c["row"], c["column"]) == (source["row"], source["column"])]
            assert value["text"] == cell["text"]
            assert value["bbox"] == cell["bbox"]
            assert value["source_page"] == field["source_page"]


@pytest.mark.parametrize("first_row", [
    ["Measurement", "10", "11", "12"],
    ["Model years", "2026", "2027", "2028"],
    ["YEAR", "2026", "2028", "2030"],
])
def test_ordinary_numeric_values_are_not_consumed_as_headers(first_row):
    matrix = [first_row, ["Result", "A", "B", "C"]]
    table = {"id": "p1-t1", "source_page": 1, "bbox": [0, 0, 400, 40],
             "role": "content", "row_count": 2, "cells": [
                 {"row": r, "column": c, "text": text, "bbox": [100*c, 20*r, 100*(c+1), 20*(r+1)]}
                 for r, row in enumerate(matrix) for c, text in enumerate(row)]}
    records = []
    _interpret_table(table, records, {})
    assert [f["description"] for f in records] == [first_row[0], "Result"]
    assert [v["text"] for v in records[0]["values"]] == first_row[1:]
    assert all(v["column_label"] is None for f in records for v in f["values"])


def test_uncoded_grid_keeps_blank_and_merged_values_and_stops_at_new_layout():
    cells = []

    def cell(row, column, text, box):
        cells.append({"row": row, "column": column, "text": text, "bbox": box})

    for c, text in enumerate(["YEAR", "2026", "2027", "2028"]):
        cell(0, c, text, [100*c, 0, 100*(c+1), 20])
    cell(1, 0, "CODE", [0, 20, 100, 40])
    cell(1, 1, "A", [100, 20, 200, 60])
    cell(1, 2, "", [200, 20, 300, 40])
    cell(1, 3, "C", [300, 20, 400, 60])
    cell(2, 0, "JAN", [0, 40, 100, 60])
    cell(2, 2, "B", [200, 40, 300, 60])
    cell(3, 0, "VIN example", [0, 60, 200, 80])
    cell(3, 2, "ABC123", [200, 60, 400, 80])
    table = {"id": "p1-t1", "source_page": 1, "bbox": [0, 0, 400, 80],
             "role": "content", "row_count": 4, "cells": cells}
    records = []
    _interpret_table(table, records, {})
    assert [f["description"] for f in records] == ["CODE", "JAN", "VIN example"]
    assert records[0]["kind"] == "field"
    assert [v["text"] for v in records[0]["values"]] == ["A", "", "C"]
    assert [(v["row_label"], v["column_label"], v["text"], v["inherited_from_merged_cell"])
            for v in records[1]["values"]] == [
        ("JAN", "2026", "A", True), ("JAN", "2027", "B", False), ("JAN", "2028", "C", True)]
    assert all(v["column_label"] is None for v in records[2]["values"])
