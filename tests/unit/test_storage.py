from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from bewerberzahlen.constants import (
    ACCEPTED_COLUMN,
    FACHBEREICH_COLUMN,
    NO_POTENTIAL_COLUMN,
    PROGRAM_COLUMN,
    PROGRAM_EXPORT_COLUMN,
    REJECTION_COLUMN,
    STATUS_COLUMN,
)
from bewerberzahlen.storage import (
    compute_content_hash,
    extract_snapshot_date,
    normalize_imported_by,
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "Bewerbungsnummer": "1",
        STATUS_COLUMN: "Akzeptiert",
        "BEW-Start": "23.04.2026",
        ACCEPTED_COLUMN: "24.04.2026",
        "Gesamtstatus": "",
        REJECTION_COLUMN: "",
        NO_POTENTIAL_COLUMN: "0",
        FACHBEREICH_COLUMN: "Technik",
        PROGRAM_COLUMN: "Informatik",
        PROGRAM_EXPORT_COLUMN: "Informatik",
    }
    row.update(overrides)
    return row


def test_content_hash_ist_unabhaengig_von_zeilenreihenfolge() -> None:
    first = pd.DataFrame(
        [
            _row(Bewerbungsnummer="1"),
            _row(Bewerbungsnummer="2", **{PROGRAM_COLUMN: "Maschinenbau"}),
        ]
    )
    second = pd.DataFrame(
        [
            _row(Bewerbungsnummer="2", **{PROGRAM_COLUMN: "Maschinenbau"}),
            _row(Bewerbungsnummer="1"),
        ]
    )

    assert compute_content_hash(first) == compute_content_hash(second)


def test_content_hash_ist_unabhaengig_von_spaltenreihenfolge() -> None:
    first = pd.DataFrame([_row()])
    second = first[list(reversed(first.columns))]

    assert compute_content_hash(first) == compute_content_hash(second)


def test_content_hash_aendert_sich_bei_inhaltsaenderung() -> None:
    first = pd.DataFrame([_row()])
    second = pd.DataFrame([_row(**{STATUS_COLUMN: "Absage"})])

    assert compute_content_hash(first) != compute_content_hash(second)


def test_normalize_imported_by_trimmt_wert() -> None:
    assert normalize_imported_by("  Nico  ") == "Nico"


def test_normalize_imported_by_erfordert_wert() -> None:
    with pytest.raises(ValueError, match="Importiert von"):
        normalize_imported_by("   ")


def test_extract_snapshot_date_liest_deutsches_datum_aus_dateiname() -> None:
    assert extract_snapshot_date("Daten 15.03.2026.xlsx") == date(2026, 3, 15)


def test_extract_snapshot_date_liest_kompaktes_datum_aus_dateiname() -> None:
    assert extract_snapshot_date("Export_110526.csv") == date(2026, 5, 11)


def test_extract_snapshot_date_nutzt_default_ohne_datum() -> None:
    fallback = date(2026, 1, 2)

    assert extract_snapshot_date("export.csv", default=fallback) == fallback
