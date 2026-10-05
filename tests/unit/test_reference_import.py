from __future__ import annotations

from dataclasses import replace
from io import BytesIO

import pandas as pd
import pytest

from bewerberzahlen.reference_import import (
    REFERENCE_SHEETS,
    ReferenceCount,
    assign_reference_programs,
    read_reference_workbook_from_bytes,
    semester_from_reference_header,
    validate_reference_counts,
)


def _workbook(*, bew: pd.DataFrame | None = None, imm: pd.DataFrame | None = None) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        if bew is not None:
            bew.to_excel(writer, sheet_name=REFERENCE_SHEETS["BEW"], index=False)
        if imm is not None:
            imm.to_excel(writer, sheet_name=REFERENCE_SHEETS["IMM"], index=False)
    return buffer.getvalue()


def test_parser_uses_selected_sources_and_excludes_totals_year_sums_and_blanks() -> None:
    content = _workbook(
        bew=pd.DataFrame(
            [
                [" Informatik ", 200, 150, "=C2/B2", 999],
                ["Maschinenbau", 0, 0, "=C3/B3", 999],
                ["Neuer Studiengang", None, None, None, 999],
                ["Fachbereich Technik", "=SUM(B2:B4)", None, None, 999],
                ["Gesamtsumme", "=SUM(B2:B4)", None, None, 999],
                ["Fußnote", "keine Zahlen", None, None, None],
            ],
            columns=["Studiengang", "BEW WiSe25/26", "Imma WiSe25/26", "Conversion", "WiSe17/18"],
        ),
        imm=pd.DataFrame(
            [["Informatik", 150, 10, "=SUM(B2:C2)"], ["Maschinenbau", 0, None, 0]],
            columns=["Studiengang", "WiSe25/26 ", "SoSe26", "Studienjahr 25/26"],
        ),
    )
    values = read_reference_workbook_from_bytes(content, "zahlen.xlsx")
    assert [(v.metric, v.semester, v.studiengang, v.count) for v in values] == [
        ("BEW", "WS2025_26", "Informatik", 200),
        ("BEW", "WS2025_26", "Maschinenbau", 0),
        ("IMM", "WS2025_26", "Informatik", 150),
        ("IMM", "SS2026", "Informatik", 10),
        ("IMM", "WS2025_26", "Maschinenbau", 0),
    ]
    assert values[0].source_cell == "B2"
    assert values[0].sheet_name == REFERENCE_SHEETS["BEW"]
    assert values[0].fachbereich == ""


@pytest.mark.parametrize("value", [-1, 1.5, True, "unbekannt", "=1+2", 2_147_483_648])
def test_parser_rejects_invalid_direct_counts_with_source(value: object) -> None:
    content = _workbook(imm=pd.DataFrame([["Informatik", value]], columns=["Name", "WiSe25/26"]))
    with pytest.raises(ValueError, match="Entwicklung Imma je Studienjahr!B2"):
        read_reference_workbook_from_bytes(content, "zahlen.xlsx", metrics=("IMM",))


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("WiSe25/26", "WS2025_26"),
        ("WiSe2025/2026", "WS2025_26"),
        (" SoSe26 ", "SS2026"),
        ("WiSe99/00", "WS2099_00"),
        ("WiSe1999/00", "WS1999_00"),
    ],
)
def test_semester_headers(header: str, expected: str) -> None:
    assert semester_from_reference_header(header) == expected


@pytest.mark.parametrize("header", ["WiSe25/27", "SoSe", "Studienjahr 25/26", "WiSe2025/2027"])
def test_invalid_semester_headers(header: str) -> None:
    with pytest.raises(ValueError, match="Ungültiges Semester"):
        semester_from_reference_header(header)


def test_metrics_can_be_imported_independently_and_missing_requested_sheet_is_error() -> None:
    content = _workbook(imm=pd.DataFrame([["Informatik", 150]], columns=["Name", "WiSe25/26"]))
    assert len(read_reference_workbook_from_bytes(content, "zahlen.xlsx", metrics=("IMM",))) == 1
    with pytest.raises(ValueError, match="Erforderlicher Reiter fehlt"):
        read_reference_workbook_from_bytes(content, "zahlen.xlsx")


@pytest.mark.parametrize("names", [["Informatik", " Informatik "], ["Alt", "Neu"]])
def test_duplicate_source_or_assigned_keys_are_rejected(names: list[str]) -> None:
    content = _workbook(
        imm=pd.DataFrame([[name, 10] for name in names], columns=["Name", "WiSe25/26"])
    )
    with pytest.raises(ValueError, match="Doppelte Referenz"):
        values = read_reference_workbook_from_bytes(content, "zahlen.xlsx", metrics=("IMM",))
        assign_reference_programs(values, {name: ("Informatik", "Technik") for name in names})


def test_duplicate_semester_headers_are_rejected() -> None:
    content = _workbook(
        imm=pd.DataFrame([["Informatik", 10, 11]], columns=["Name", "WiSe25/26", " WiSe25/26 "])
    )
    with pytest.raises(ValueError, match="Semester kommt mehrfach vor"):
        read_reference_workbook_from_bytes(content, "zahlen.xlsx", metrics=("IMM",))


def test_assignments_require_a_target_and_valid_department_and_preserve_provenance() -> None:
    value = ReferenceCount("WS2025_26", "Alt", "IMM", 150, REFERENCE_SHEETS["IMM"], "B2")
    with pytest.raises(ValueError, match="noch nicht zugeordnet"):
        assign_reference_programs([value], {})
    with pytest.raises(ValueError, match="Fachbereich"):
        assign_reference_programs([value], {"Alt": ("Informatik", "Unbekannt")})
    assigned = assign_reference_programs([value], {"Alt": ("Informatik", "Technik")})
    assert assigned == [replace(value, studiengang="Informatik", fachbereich="Technik")]
    assert value.studiengang == "Alt"


def test_empty_workbook_values_and_invalid_filename_are_rejected() -> None:
    with pytest.raises(ValueError, match="XLSX"):
        read_reference_workbook_from_bytes(b"", "zahlen.csv")
    content = _workbook(imm=pd.DataFrame([["Informatik", None]], columns=["Name", "WiSe25/26"]))
    with pytest.raises(ValueError, match="Keine expliziten Semesterzahlen"):
        read_reference_workbook_from_bytes(content, "zahlen.xlsx", metrics=("IMM",))


def test_storage_validation_rejects_unassigned_and_invalid_counts() -> None:
    value = ReferenceCount("WS2025_26", "Informatik", "IMM", 0, "Quelle", "B2")
    with pytest.raises(ValueError, match="Fachbereich"):
        validate_reference_counts([value])
    with pytest.raises(ValueError, match="Anzahl"):
        validate_reference_counts([replace(value, count=-1, fachbereich="Technik")])
