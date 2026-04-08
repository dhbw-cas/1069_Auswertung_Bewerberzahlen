from __future__ import annotations

import pandas as pd

from bewerberzahlen.constants import (
    ACCEPTED_COLUMN,
    EMAIL_COLUMN,
    FACHBEREICH_COLUMN,
    NO_POTENTIAL_COLUMN,
    PROGRAM_COLUMN,
    REJECTION_COLUMN,
    STATUS_COLUMN,
)
from bewerberzahlen.mapping import ProgramEntry, ProgramResolver
from bewerberzahlen.pipeline import PipelineConfig, process_dataframe


def _resolver() -> ProgramResolver:
    return ProgramResolver.from_programs(
        [
            ProgramEntry(name="Informatik", fachbereich="Technik", aliases=[]),
            ProgramEntry(
                name="Marketing and Business Psychology", fachbereich="Wirtschaft", aliases=[]
            ),
        ]
    )


def _base_row(**overrides: object) -> dict[str, object]:
    row = {
        "Bewerbungsnummer": 1,
        STATUS_COLUMN: "",
        "BEW-Start": "2026-03-15",
        ACCEPTED_COLUMN: "",
        "Gesamtstatus": "",
        REJECTION_COLUMN: "",
        NO_POTENTIAL_COLUMN: "",
        FACHBEREICH_COLUMN: "",
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
        EMAIL_COLUMN: "max@example.com",
    }
    row.update(overrides)
    return row


def _df(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_dubletten_entfernt_and_aufbewahrt_erste() -> None:
    data = _df(
        [
            _base_row(Bewerbungsnummer=1, EMAIL_COLUMN="a@example.com"),
            _base_row(Bewerbungsnummer=2, EMAIL_COLUMN="a@example.com"),
        ]
    )
    result = process_dataframe(data, _resolver())

    assert result.cleaned is not None
    assert len(result.cleaned) == 1
    assert len(result.duplicates) == 1
    assert not result.errors


def test_status_wird_abgeleitet() -> None:
    data = _df(
        [
            _base_row(
                Bewerbungsnummer=1,
                **{EMAIL_COLUMN: "a1@example.com", ACCEPTED_COLUMN: "2026-03-16"},
            ),
            _base_row(
                Bewerbungsnummer=2,
                **{EMAIL_COLUMN: "a2@example.com", REJECTION_COLUMN: "2026-03-17"},
            ),
            _base_row(
                Bewerbungsnummer=3,
                **{EMAIL_COLUMN: "a3@example.com", NO_POTENTIAL_COLUMN: 1},
            ),
        ]
    )
    result = process_dataframe(data, _resolver())

    assert result.cleaned is not None
    statuses = list(result.cleaned[STATUS_COLUMN])
    assert statuses == ["Akzeptiert", "Absage", "Kein Potential"]


def test_mehrfach_status_fuehrt_zu_fehler() -> None:
    data = _df(
        [
            _base_row(
                Bewerbungsnummer=1,
                **{ACCEPTED_COLUMN: "2026-03-16", REJECTION_COLUMN: "2026-03-17"},
            )
        ]
    )
    result = process_dataframe(data, _resolver())

    assert result.cleaned is not None
    assert not result.errors
    assert result.cleaned[STATUS_COLUMN].iloc[0] == "Absage"


def test_unknown_program_ergibt_fehler() -> None:
    data = _df([_base_row(Bewerbungsnummer=1, **{PROGRAM_COLUMN: "Unbekannt"})])
    result = process_dataframe(data, _resolver())

    assert result.cleaned is None
    assert any("Unbekannt" in issue.message for issue in result.errors)


def test_leerer_studiengang_wird_ignoriert_aber_gemeldet() -> None:
    data = _df(
        [
            _base_row(Bewerbungsnummer=1, **{PROGRAM_COLUMN: ""}),
            _base_row(
                Bewerbungsnummer=2, **{PROGRAM_COLUMN: "Informatik", EMAIL_COLUMN: "b@example.com"}
            ),
        ]
    )
    result = process_dataframe(data, _resolver())

    assert result.cleaned is not None
    assert len(result.cleaned) == 1
    assert result.cleaned[PROGRAM_COLUMN].iloc[0] == "Informatik"
    assert any("Studiengang fehlt" in issue.message for issue in result.warnings)


def test_manuelle_zuordnung_erlaubt_unbekannten_studiengang() -> None:
    data = _df([_base_row(Bewerbungsnummer=1, **{PROGRAM_COLUMN: "Neu"})])
    cfg = PipelineConfig(manual_assignments={"Neu": "Technik"})
    result = process_dataframe(data, _resolver(), cfg)

    assert result.cleaned is not None
    assert not result.errors
    assert result.cleaned[FACHBEREICH_COLUMN].iloc[0] == "Technik"


def test_pii_wird_entfernt() -> None:
    data = _df([_base_row()])
    result = process_dataframe(data, _resolver())

    assert result.cleaned is not None
    pii_cols = {
        "Formularfelder_Vorname",
        "Formularfelder_Name",
        "Formularfelder_Strasse_und_Hausnummer",
        "Formularfelder_Ort",
        "Formularfelder_Telefon_mobil",
        EMAIL_COLUMN,
    }
    assert pii_cols.isdisjoint(result.cleaned.columns)
