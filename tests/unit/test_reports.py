from __future__ import annotations

import pandas as pd

from bewerberzahlen.reports import (
    ACCEPTED_COLUMN,
    NO_POTENTIAL_COLUMN,
    OPEN_COLUMN,
    PER_DATO_COLUMN,
    PLACEHOLDER_COLUMNS,
    PLACEHOLDER_VALUE,
    PROGRAM_COLUMN,
    REJECTIONS_COLUMN,
    build_bewerbungszahlen_wise_report,
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


def _row(fachbereich: str, studiengang: str, status: str, anzahl: int) -> dict[str, object]:
    return {
        "semester": "WS2026_27",
        "fachbereich": fachbereich,
        "studiengang": studiengang,
        "status": status,
        "anzahl": anzahl,
    }
