from __future__ import annotations

from datetime import date

import pandas as pd

from bewerberzahlen.reports import (
    ACCEPTED_COLUMN,
    ACCEPTED_DELTA_COLUMN,
    ACCEPTED_DELTA_PERCENT_COLUMN,
    ACCEPTED_PREVIOUS_YEAR_COLUMN,
    NO_POTENTIAL_COLUMN,
    OPEN_COLUMN,
    PER_DATO_COLUMN,
    PLACEHOLDER_COLUMNS,
    PLACEHOLDER_VALUE,
    PROGRAM_COLUMN,
    REJECTIONS_COLUMN,
    build_bewerbungszahlen_wise_report,
    previous_year_report_date,
)


def test_bewerbungszahlen_wise_report_berechnet_statusspalten() -> None:
    dashboard_rows = pd.DataFrame(
        [
            _row("Technik", "Informatik", "Akzeptiert", 4),
            _row("Technik", "Informatik", "Offen", 3),
            _row("Technik", "Informatik", "Kein Potential", 2),
            _row("Technik", "Informatik", "Absage", 1),
        ]
    )

    report = build_bewerbungszahlen_wise_report(dashboard_rows)
    row = report[report[PROGRAM_COLUMN] == "Informatik"].iloc[0]

    assert row[PER_DATO_COLUMN] == 7
    assert row[ACCEPTED_COLUMN] == 4
    assert row[OPEN_COLUMN] == 3
    assert row[NO_POTENTIAL_COLUMN] == 2
    assert row[REJECTIONS_COLUMN] == 1


def test_bewerbungszahlen_wise_report_berechnet_summen() -> None:
    dashboard_rows = pd.DataFrame(
        [
            _row("Technik", "Informatik", "Akzeptiert", 4),
            _row("Technik", "Informatik", "Offen", 3),
            _row("Technik", "Maschinenbau", "Akzeptiert", 2),
            _row("Wirtschaft", "Finance", "Offen", 5),
        ]
    )

    report = build_bewerbungszahlen_wise_report(dashboard_rows)
    technik = report[report[PROGRAM_COLUMN] == "Fachbereich Technik"].iloc[0]
    total = report[report[PROGRAM_COLUMN] == "Gesamtsumme"].iloc[0]

    assert technik[PER_DATO_COLUMN] == 9
    assert technik[ACCEPTED_COLUMN] == 6
    assert technik[OPEN_COLUMN] == 3
    assert total[PER_DATO_COLUMN] == 14
    assert total[ACCEPTED_COLUMN] == 6
    assert total[OPEN_COLUMN] == 8


def test_bewerbungszahlen_wise_report_enthaelt_placeholder_spalten() -> None:
    dashboard_rows = pd.DataFrame([_row("Technik", "Informatik", "Akzeptiert", 1)])

    report = build_bewerbungszahlen_wise_report(dashboard_rows)
    row = report[report[PROGRAM_COLUMN] == "Informatik"].iloc[0]

    for column in PLACEHOLDER_COLUMNS:
        assert column in report.columns
        assert row[column] == PLACEHOLDER_VALUE


def test_bewerbungszahlen_wise_report_behandelt_unbekannte_status_als_offen() -> None:
    dashboard_rows = pd.DataFrame([_row("Technik", "Informatik", "Abgeschickt", 2)])

    report = build_bewerbungszahlen_wise_report(dashboard_rows)
    row = report[report[PROGRAM_COLUMN] == "Informatik"].iloc[0]

    assert row[PER_DATO_COLUMN] == 2
    assert row[OPEN_COLUMN] == 2


def test_bewerbungszahlen_wise_report_berechnet_akzeptiert_vorjahr_und_delta() -> None:
    current_rows = pd.DataFrame(
        [
            _row("Technik", "Informatik", "Akzeptiert", 6),
            _row("Technik", "Maschinenbau", "Akzeptiert", 2),
        ]
    )
    previous_year_rows = pd.DataFrame(
        [
            _row("Technik", "Informatik", "Akzeptiert", 4),
            _row("Technik", "Maschinenbau", "Offen", 3),
            _row("Technik", "Ehemaliger Studiengang", "Akzeptiert", 7),
        ]
    )

    report = build_bewerbungszahlen_wise_report(current_rows, previous_year_rows)
    informatik = report[report[PROGRAM_COLUMN] == "Informatik"].iloc[0]
    maschinenbau = report[report[PROGRAM_COLUMN] == "Maschinenbau"].iloc[0]
    technik = report[report[PROGRAM_COLUMN] == "Fachbereich Technik"].iloc[0]
    total = report[report[PROGRAM_COLUMN] == "Gesamtsumme"].iloc[0]

    assert informatik[ACCEPTED_PREVIOUS_YEAR_COLUMN] == 4
    assert informatik[ACCEPTED_DELTA_COLUMN] == 2
    assert informatik[ACCEPTED_DELTA_PERCENT_COLUMN] == 50.0
    assert maschinenbau[ACCEPTED_PREVIOUS_YEAR_COLUMN] == 0
    assert maschinenbau[ACCEPTED_DELTA_COLUMN] == 2
    assert maschinenbau[ACCEPTED_DELTA_PERCENT_COLUMN] == PLACEHOLDER_VALUE
    assert technik[ACCEPTED_PREVIOUS_YEAR_COLUMN] == 4
    assert technik[ACCEPTED_DELTA_COLUMN] == 4
    assert technik[ACCEPTED_DELTA_PERCENT_COLUMN] == 100.0
    assert total[ACCEPTED_PREVIOUS_YEAR_COLUMN] == 4
    assert "Ehemaliger Studiengang" not in report[PROGRAM_COLUMN].tolist()


def test_bewerbungszahlen_wise_report_behandelt_leere_vorjahresauswahl_als_null() -> None:
    current_rows = pd.DataFrame([_row("Technik", "Informatik", "Akzeptiert", 3)])

    report = build_bewerbungszahlen_wise_report(current_rows, pd.DataFrame())
    row = report[report[PROGRAM_COLUMN] == "Informatik"].iloc[0]

    assert row[ACCEPTED_PREVIOUS_YEAR_COLUMN] == 0
    assert row[ACCEPTED_DELTA_COLUMN] == 3
    assert row[ACCEPTED_DELTA_PERCENT_COLUMN] == PLACEHOLDER_VALUE


def test_previous_year_report_date_behandelt_normalen_stichtag_und_schaltjahr() -> None:
    assert previous_year_report_date(date(2026, 8, 31)) == date(2025, 8, 31)
    assert previous_year_report_date(date(2024, 2, 29)) == date(2023, 2, 28)


def _row(fachbereich: str, studiengang: str, status: str, anzahl: int) -> dict[str, object]:
    return {
        "semester": "WS2026_27",
        "fachbereich": fachbereich,
        "studiengang": studiengang,
        "status": status,
        "anzahl": anzahl,
    }
