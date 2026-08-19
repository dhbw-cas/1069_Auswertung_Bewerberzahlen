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


def test_dubletten_erfordern_auswahl() -> None:
    data = _df(
        [
            _base_row(Bewerbungsnummer=1, **{EMAIL_COLUMN: "a@example.com"}),
            _base_row(Bewerbungsnummer=2, **{EMAIL_COLUMN: "a@example.com"}),
        ]
    )
    result = process_dataframe(data, _resolver())

    assert result.cleaned is None
    assert len(result.duplicates) == 2
    assert not result.errors
    assert len(result.duplicate_groups) == 1
    assert sorted(result.duplicate_groups[0]) == [2, 3]
    assert any("Bitte pro Gruppe" in issue.message for issue in result.warnings)
    assert result.n_input == 2
    assert result.n_kept == 0
    assert result.n_duplicates == 1
    assert result.n_missing_program == 0
    assert result.n_unknown_program == 0


def test_dubletten_auswahl_behaelt_gewaehlte_zeile() -> None:
    data = _df(
        [
            _base_row(Bewerbungsnummer=1, **{EMAIL_COLUMN: "a@example.com"}),
            _base_row(Bewerbungsnummer=2, **{EMAIL_COLUMN: "a@example.com"}),
        ]
    )
    cfg = PipelineConfig(duplicate_keep_rows={3})
    result = process_dataframe(data, _resolver(), cfg)

    assert result.cleaned is not None
    assert len(result.cleaned) == 1
    assert result.cleaned["Bewerbungsnummer"].iloc[0] == 2
    assert len(result.duplicates) == 1
    assert result.n_kept == 1
    assert result.n_duplicates == 1


def test_gleiche_email_unterschiedlicher_studiengang_ist_keine_dublette() -> None:
    data = _df(
        [
            _base_row(
                Bewerbungsnummer=1,
                **{EMAIL_COLUMN: "a@example.com", PROGRAM_COLUMN: "Informatik"},
            ),
            _base_row(
                Bewerbungsnummer=2,
                **{
                    EMAIL_COLUMN: "a@example.com",
                    PROGRAM_COLUMN: "Marketing and Business Psychology",
                },
            ),
        ]
    )
    result = process_dataframe(data, _resolver())

    assert result.cleaned is not None
    assert len(result.cleaned) == 2
    assert result.n_duplicates == 0
    assert not result.duplicate_groups


def test_dreifach_dublette_behaelt_nur_ausgewaehlte_zeile() -> None:
    data = _df(
        [
            _base_row(Bewerbungsnummer=1, **{EMAIL_COLUMN: "a@example.com"}),
            _base_row(Bewerbungsnummer=2, **{EMAIL_COLUMN: "a@example.com"}),
            _base_row(Bewerbungsnummer=3, **{EMAIL_COLUMN: "a@example.com"}),
        ]
    )
    cfg = PipelineConfig(duplicate_keep_rows={3})
    result = process_dataframe(data, _resolver(), cfg)

    assert result.cleaned is not None
    assert len(result.cleaned) == 1
    assert result.cleaned["Bewerbungsnummer"].iloc[0] == 2
    assert len(result.duplicates) == 2
    assert result.n_duplicates == 2


def test_leere_emails_unterschiedlicher_namen_sind_keine_dubletten() -> None:
    data = _df(
        [
            _base_row(
                Bewerbungsnummer=1,
                Formularfelder_Vorname="Max",
                Formularfelder_Name="Mustermann",
                **{EMAIL_COLUMN: ""},
            ),
            _base_row(
                Bewerbungsnummer=2,
                Formularfelder_Vorname="Erika",
                Formularfelder_Name="Musterfrau",
                **{EMAIL_COLUMN: ""},
            ),
        ]
    )

    result = process_dataframe(data, _resolver())

    assert result.cleaned is not None
    assert len(result.cleaned) == 2
    assert not result.duplicate_groups


def test_leere_emails_gleichen_vollstaendigen_namen_normalisiert() -> None:
    data = _df(
        [
            _base_row(
                Bewerbungsnummer=1,
                Formularfelder_Vorname="  Max   Maria ",
                Formularfelder_Name="Müller",
                **{EMAIL_COLUMN: None},
            ),
            _base_row(
                Bewerbungsnummer=2,
                Formularfelder_Vorname="max maria",
                Formularfelder_Name="MÜLLER",
                **{EMAIL_COLUMN: pd.NA},
            ),
        ]
    )

    result = process_dataframe(data, _resolver())

    assert result.cleaned is None
    assert result.duplicate_groups == [[2, 3]]


def test_name_wird_genutzt_wenn_nur_eine_email_leer_ist() -> None:
    data = _df(
        [
            _base_row(Bewerbungsnummer=1, **{EMAIL_COLUMN: "max@example.com"}),
            _base_row(Bewerbungsnummer=2, **{EMAIL_COLUMN: ""}),
        ]
    )

    result = process_dataframe(data, _resolver())

    assert result.cleaned is None
    assert result.duplicate_groups == [[2, 3]]


def test_gleicher_name_mit_unterschiedlichen_ausgefuellten_emails_ist_keine_dublette() -> None:
    data = _df(
        [
            _base_row(Bewerbungsnummer=1, **{EMAIL_COLUMN: "max1@example.com"}),
            _base_row(Bewerbungsnummer=2, **{EMAIL_COLUMN: "max2@example.com"}),
        ]
    )

    result = process_dataframe(data, _resolver())

    assert result.cleaned is not None
    assert len(result.cleaned) == 2
    assert not result.duplicate_groups


def test_gleiche_email_bleibt_bei_unterschiedlichen_namen_dublette() -> None:
    data = _df(
        [
            _base_row(
                Bewerbungsnummer=1,
                Formularfelder_Vorname="Max",
                Formularfelder_Name="Mustermann",
                **{EMAIL_COLUMN: "shared@example.com"},
            ),
            _base_row(
                Bewerbungsnummer=2,
                Formularfelder_Vorname="Erika",
                Formularfelder_Name="Musterfrau",
                **{EMAIL_COLUMN: "shared@example.com"},
            ),
        ]
    )

    result = process_dataframe(data, _resolver())

    assert result.cleaned is None
    assert result.duplicate_groups == [[2, 3]]


def test_leere_email_mit_unvollstaendigem_namen_ist_keine_dublette() -> None:
    data = _df(
        [
            _base_row(Bewerbungsnummer=1, Formularfelder_Name="", **{EMAIL_COLUMN: ""}),
            _base_row(Bewerbungsnummer=2, Formularfelder_Name="", **{EMAIL_COLUMN: ""}),
        ]
    )

    result = process_dataframe(data, _resolver())

    assert result.cleaned is not None
    assert len(result.cleaned) == 2
    assert not result.duplicate_groups


def test_email_und_namens_treffer_werden_zu_einer_gruppe_verbunden() -> None:
    data = _df(
        [
            _base_row(
                Bewerbungsnummer=1,
                Formularfelder_Vorname="Andere",
                Formularfelder_Name="Person",
                **{EMAIL_COLUMN: "shared@example.com"},
            ),
            _base_row(Bewerbungsnummer=2, **{EMAIL_COLUMN: "shared@example.com"}),
            _base_row(Bewerbungsnummer=3, **{EMAIL_COLUMN: ""}),
        ]
    )

    result = process_dataframe(data, _resolver())

    assert result.cleaned is None
    assert result.duplicate_groups == [[2, 3, 4]]
    assert result.n_duplicates == 2


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
    assert result.n_unknown_program == 0


def test_unknown_program_ergibt_fehler() -> None:
    data = _df([_base_row(Bewerbungsnummer=1, **{PROGRAM_COLUMN: "Unbekannt"})])
    result = process_dataframe(data, _resolver())

    assert result.cleaned is None
    assert any("Unbekannt" in issue.message for issue in result.errors)
    assert result.n_unknown_program == 1


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
    assert result.n_missing_program == 1
    assert result.n_kept == 1


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
