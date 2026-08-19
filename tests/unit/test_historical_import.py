from __future__ import annotations

from datetime import date
from io import BytesIO

import pandas as pd
import pytest

from bewerberzahlen.constants import (
    ACCEPTED_COLUMN,
    FACHBEREICH_COLUMN,
    NO_POTENTIAL_COLUMN,
    PROGRAM_COLUMN,
    REJECTION_COLUMN,
    STATUS_COLUMN,
)
from bewerberzahlen.historical_import import read_historical_workbook_from_bytes
from bewerberzahlen.mapping import ProgramEntry, ProgramResolver
from bewerberzahlen.pipeline import process_dataframe


def _raw_row(
    *,
    start_column: str = "Formular_Start_Datum",
    accepted_column: str = "Formular_Akzeptiert_Datum",
    rejection_column: str = "Formularfelder_Abgesagt_am",
    no_potential_column: str = "Formularfelder_Kein_Potential",
    fachbereich_column: str = "Fachbereich",
) -> dict[str, object]:
    return {
        "Bewerbungsnummer": "1",
        STATUS_COLUMN: "Abgeschickt",
        start_column: "15.07.2025",
        accepted_column: "16.07.2025",
        "Gesamtstatus": "",
        rejection_column: "",
        no_potential_column: "0",
        fachbereich_column: "",
        PROGRAM_COLUMN: "Informatik",
        "Formularfelder_Studiengang_Export": "Informatik",
        "Formularfelder_Anrede": "Herr",
        "Formularfelder_Vorname": "Max",
        "Formularfelder_Name": "Mustermann",
        "Formularfelder_Strasse_und_Hausnummer": "Hauptstr. 1",
        "Formularfelder_Postleitzahl": "12345",
        "Formularfelder_Ort": "Berlin",
        "Formularfelder_Land": "Deutschland",
        "Formularfelder_Telefon_mobil": "01234",
        "Formularfelder_E-Mail_privat": "max@example.com",
    }


def _workbook_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, dataframe in sheets.items():
            dataframe.to_excel(writer, sheet_name=sheet_name, index=False)
    return buffer.getvalue()


def test_historical_workbook_laesst_nur_datenreiter_zu_und_sortiert_sie() -> None:
    content = _workbook_bytes(
        {
            "Daten 15.01.2026": pd.DataFrame([_raw_row()]),
            "Pivot 15.01.2026": pd.DataFrame([{"Wert": 1}]),
            "Daten 31.07.25": pd.DataFrame([_raw_row()]),
            "Datenbasis_Vorjahr": pd.DataFrame([_raw_row()]),
        }
    )

    datasets = read_historical_workbook_from_bytes(content, "historisch.xlsx")

    assert [dataset.sheet_name for dataset in datasets] == [
        "Daten 31.07.25",
        "Daten 15.01.2026",
    ]
    assert [dataset.report_date for dataset in datasets] == [
        date(2025, 7, 31),
        date(2026, 1, 15),
    ]


@pytest.mark.parametrize(
    (
        "start_column",
        "accepted_column",
        "rejection_column",
        "no_potential_column",
        "fachbereich_column",
    ),
    [
        (
            "Formular_Start_Datum",
            "Formular_Akzeptiert_Datum",
            "Formularfelder_Abgesagt_am",
            "Formularfelder_Kein_Potential",
            "Fachbereich",
        ),
        ("Start", "Akzeptiert", "Absage", "Kein Potential", "FB"),
        ("Start_Datum", "Akzeptiert_Datum", "Abgesagt_am", "Kein_Potential", "Fachbereich"),
    ],
)
def test_historical_workbook_normalisiert_historische_spaltenvarianten(
    start_column: str,
    accepted_column: str,
    rejection_column: str,
    no_potential_column: str,
    fachbereich_column: str,
) -> None:
    content = _workbook_bytes(
        {
            "Daten 15.12.2025": pd.DataFrame(
                [
                    _raw_row(
                        start_column=start_column,
                        accepted_column=accepted_column,
                        rejection_column=rejection_column,
                        no_potential_column=no_potential_column,
                        fachbereich_column=fachbereich_column,
                    )
                ]
            )
        }
    )

    dataframe = read_historical_workbook_from_bytes(content, "historisch.xlsx")[0].dataframe

    assert "BEW-Start" in dataframe
    assert ACCEPTED_COLUMN in dataframe
    assert REJECTION_COLUMN in dataframe
    assert NO_POTENTIAL_COLUMN in dataframe
    assert FACHBEREICH_COLUMN in dataframe
    assert dataframe.loc[0, "BEW-Start"] == "15.07.2025"


def test_historical_workbook_durchlaeuft_regulaere_pipeline() -> None:
    content = _workbook_bytes(
        {
            "Daten 15.01.2026": pd.DataFrame(
                [
                    _raw_row(
                        start_column="Start_Datum",
                        accepted_column="Akzeptiert_Datum",
                        rejection_column="Abgesagt_am",
                        no_potential_column="Kein_Potential",
                    )
                ]
            )
        }
    )
    resolver = ProgramResolver.from_programs(
        [ProgramEntry(name="Informatik", fachbereich="Technik", aliases=[])]
    )

    dataset = read_historical_workbook_from_bytes(content, "historisch.xlsx")[0]
    result = process_dataframe(dataset.dataframe, resolver)

    assert result.cleaned is not None
    assert result.cleaned.loc[0, STATUS_COLUMN] == "Akzeptiert"
    assert result.cleaned.loc[0, FACHBEREICH_COLUMN] == "Technik"
    assert "Formularfelder_Vorname" not in result.cleaned
    assert "Formularfelder_E-Mail_privat" not in result.cleaned


def test_historical_workbook_lehnt_doppelten_stichtag_ab() -> None:
    content = _workbook_bytes(
        {
            "Daten 31.07.25": pd.DataFrame([_raw_row()]),
            "Daten 31.07.2025": pd.DataFrame([_raw_row()]),
        }
    )

    with pytest.raises(ValueError, match="kommt mehrfach vor"):
        read_historical_workbook_from_bytes(content, "historisch.xlsx")


def test_historical_workbook_lehnt_mappe_ohne_datenreiter_ab() -> None:
    content = _workbook_bytes({"Pivot 31.07.25": pd.DataFrame([{"Wert": 1}])})

    with pytest.raises(ValueError, match="Keine Datenreiter"):
        read_historical_workbook_from_bytes(content, "historisch.xlsx")


def test_historical_workbook_lehnt_falsches_dateiformat_ab() -> None:
    with pytest.raises(ValueError, match="XLSX"):
        read_historical_workbook_from_bytes(b"Inhalt", "historisch.xls")
