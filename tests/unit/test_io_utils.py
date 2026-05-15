from __future__ import annotations

from bewerberzahlen.constants import (
    ACCEPTED_COLUMN,
    FACHBEREICH_COLUMN,
    NO_POTENTIAL_COLUMN,
    PROGRAM_COLUMN,
    REJECTION_COLUMN,
    STATUS_COLUMN,
)
from bewerberzahlen.io_utils import read_import_csv_from_bytes
from bewerberzahlen.mapping import ProgramEntry, ProgramResolver
from bewerberzahlen.pipeline import process_dataframe


def _csv_bytes(rows: list[str]) -> bytes:
    return "\n".join(rows).encode("cp1252")


def test_import_csv_mapped_neues_exportformat_auf_interne_spalten() -> None:
    content = _csv_bytes(
        [
            ";".join(
                [
                    "Bewerbungsnummer",
                    "Status",
                    "Formular_Start_Datum",
                    "Formular_Akzeptiert_Datum",
                    "Gesamtstatus",
                    "Formularfelder_Abgesagt_am",
                    "Formularfelder_Kein_Potential",
                    "Formularfelder_Hauptfach_Prüfungsordnung",
                    "Formularfelder_Studiengang_Export",
                    "Formularfelder_Anrede",
                    "Formularfelder_Vorname",
                    "Formularfelder_Name",
                    "Formularfelder_Strasse_und_Hausnummer",
                    "Formularfelder_Postleitzahl",
                    "Formularfelder_Ort",
                    "Formularfelder_Land",
                    "Formularfelder_Telefon_mobil",
                    "Formularfelder_E-Mail_privat",
                ]
            ),
            ";".join(
                [
                    "1",
                    "Abgeschickt",
                    "23.04.2026",
                    "24.04.2026",
                    "",
                    "",
                    "0",
                    "Informatik",
                    "",
                    "Herr",
                    "Max",
                    "Müller",
                    "Hauptstr. 1",
                    "12345",
                    "Berlin",
                    "Deutschland",
                    "01234",
                    "max@example.com",
                ]
            ),
        ]
    )

    df = read_import_csv_from_bytes(content)

    assert "BEW-Start" in df.columns
    assert ACCEPTED_COLUMN in df.columns
    assert REJECTION_COLUMN in df.columns
    assert NO_POTENTIAL_COLUMN in df.columns
    assert FACHBEREICH_COLUMN in df.columns
    assert "Formular_Start_Datum" not in df.columns
    assert "Formular_Akzeptiert_Datum" not in df.columns
    assert df.loc[0, "BEW-Start"] == "23.04.2026"
    assert df.loc[0, ACCEPTED_COLUMN] == "24.04.2026"
    assert df.loc[0, FACHBEREICH_COLUMN] == ""
    assert df.loc[0, PROGRAM_COLUMN] == "Informatik"


def test_import_csv_normalisierte_daten_laufen_durch_pipeline() -> None:
    content = _csv_bytes(
        [
            (
                "Bewerbungsnummer;Status;Formular_Start_Datum;Formular_Akzeptiert_Datum;"
                "Gesamtstatus;Formularfelder_Abgesagt_am;Formularfelder_Kein_Potential;"
                "Formularfelder_Hauptfach_Prüfungsordnung;Formularfelder_Studiengang_Export;"
                "Formularfelder_Anrede;Formularfelder_Vorname;Formularfelder_Name;"
                "Formularfelder_Strasse_und_Hausnummer;Formularfelder_Postleitzahl;"
                "Formularfelder_Ort;Formularfelder_Land;Formularfelder_Telefon_mobil;"
                "Formularfelder_E-Mail_privat"
            ),
            (
                "1;Abgeschickt;23.04.2026;24.04.2026;;;0;Informatik;;Herr;Max;"
                "Müller;Hauptstr. 1;12345;Berlin;Deutschland;01234;max@example.com"
            ),
        ]
    )
    resolver = ProgramResolver.from_programs(
        [ProgramEntry(name="Informatik", fachbereich="Technik", aliases=[])]
    )

    result = process_dataframe(read_import_csv_from_bytes(content), resolver)

    assert result.cleaned is not None
    assert not result.errors
    assert result.cleaned[STATUS_COLUMN].iloc[0] == "Akzeptiert"
    assert result.cleaned[FACHBEREICH_COLUMN].iloc[0] == "Technik"
    assert "Formularfelder_Vorname" not in result.cleaned.columns
