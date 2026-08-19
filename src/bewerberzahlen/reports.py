from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import cast

import pandas as pd


@dataclass(frozen=True)
class ReportDefinition:
    id: str
    label: str


OVERVIEW_REPORT_ID = "overview"
BEWERBUNGSZAHLEN_WISE_REPORT_ID = "bewerbungszahlen_wise"

REPORT_DEFINITIONS = (
    ReportDefinition(id=OVERVIEW_REPORT_ID, label="Übersicht"),
    ReportDefinition(id=BEWERBUNGSZAHLEN_WISE_REPORT_ID, label="Bewerbungszahlen WiSe"),
)

PROGRAM_COLUMN = "Studiengang / Bereich"
ROW_TYPE_COLUMN = "Zeilentyp"
PER_DATO_COLUMN = "per dato"
ACCEPTED_COLUMN = "davon akzeptiert"
OPEN_COLUMN = "davon offen"
NO_POTENTIAL_COLUMN = "kein Potential"
REJECTIONS_COLUMN = "Absagen"
ACCEPTED_PREVIOUS_YEAR_COLUMN = "Akzeptiert VJ per dato"
ACCEPTED_DELTA_COLUMN = "Akzeptiert Δ"
ACCEPTED_DELTA_PERCENT_COLUMN = "Akzeptiert Δ %"

PLACEHOLDER_COLUMNS = [
    ACCEPTED_PREVIOUS_YEAR_COLUMN,
    ACCEPTED_DELTA_COLUMN,
    ACCEPTED_DELTA_PERCENT_COLUMN,
    "Alle Bewerbungen VJ per dato",
    "Alle Bewerbungen Δ",
    "Alle Bewerbungen Δ %",
    "Prognose BEW",
    "Prognose IMM",
    "BEW VJ final",
    "Zielerreichung per dato/final",
    "IMM VJ final",
    "Wandlung IMM/BEW",
    "IMM VJ",
    "Zielwert",
    "Vergleich Zielwert",
    "Zielerreichung per dato",
]

REPORT_COLUMNS = [
    PROGRAM_COLUMN,
    PER_DATO_COLUMN,
    ACCEPTED_COLUMN,
    OPEN_COLUMN,
    NO_POTENTIAL_COLUMN,
    REJECTIONS_COLUMN,
    *PLACEHOLDER_COLUMNS,
    ROW_TYPE_COLUMN,
]

FACHBEREICH_ORDER = ("Gesundheit", "Sozialwesen", "Technik", "Wirtschaft")
PLACEHOLDER_VALUE = "-"


def build_bewerbungszahlen_wise_report(
    dashboard_rows: pd.DataFrame,
    previous_year_rows: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if dashboard_rows.empty:
        return pd.DataFrame(columns=REPORT_COLUMNS)

    rows: list[dict[str, object]] = []
    prepared = _prepare_status_counts(dashboard_rows)
    if previous_year_rows is not None:
        prepared = _add_previous_year_accepted(prepared, previous_year_rows)
    for fachbereich in _ordered_fachbereiche(prepared):
        fachbereich_rows = prepared[prepared["fachbereich"] == fachbereich].copy()
        sorted_rows = fachbereich_rows.sort_values(by="studiengang")
        for _, row in sorted_rows.iterrows():
            rows.append(_report_row(str(row["studiengang"]), row, "Studiengang"))
        rows.append(_summary_row(_fachbereich_label(fachbereich), fachbereich_rows, "Fachbereich"))

    rows.append(_summary_row("Gesamtsumme", prepared, "Gesamtsumme"))
    return pd.DataFrame(rows, columns=REPORT_COLUMNS)


def previous_year_report_date(report_date: date) -> date:
    try:
        return report_date.replace(year=report_date.year - 1)
    except ValueError:
        return report_date.replace(year=report_date.year - 1, day=28)


def _prepare_status_counts(dashboard_rows: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        dashboard_rows.groupby(["fachbereich", "studiengang", "status"], as_index=False)["anzahl"]
        .sum()
        .copy()
    )
    grouped["status_bucket"] = grouped["status"].map(_status_bucket)
    pivot = grouped.pivot_table(
        index=["fachbereich", "studiengang"],
        columns="status_bucket",
        values="anzahl",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()

    for column in (ACCEPTED_COLUMN, NO_POTENTIAL_COLUMN, REJECTIONS_COLUMN, "sonstige"):
        if column not in pivot:
            pivot[column] = 0

    pivot[OPEN_COLUMN] = pivot["sonstige"].astype(int)
    pivot[PER_DATO_COLUMN] = pivot[ACCEPTED_COLUMN].astype(int) + pivot[OPEN_COLUMN].astype(int)
    return cast(
        pd.DataFrame,
        pivot[
            [
                "fachbereich",
                "studiengang",
                PER_DATO_COLUMN,
                ACCEPTED_COLUMN,
                OPEN_COLUMN,
                NO_POTENTIAL_COLUMN,
                REJECTIONS_COLUMN,
            ]
        ].copy(),
    )


def _status_bucket(status: object) -> str:
    normalized = str(status).strip().lower()
    if normalized == "akzeptiert":
        return ACCEPTED_COLUMN
    if normalized == "kein potential":
        return NO_POTENTIAL_COLUMN
    if normalized == "absage":
        return REJECTIONS_COLUMN
    return "sonstige"


def _add_previous_year_accepted(
    current_rows: pd.DataFrame, previous_year_rows: pd.DataFrame
) -> pd.DataFrame:
    if previous_year_rows.empty:
        with_previous_year = current_rows.copy()
        with_previous_year[ACCEPTED_PREVIOUS_YEAR_COLUMN] = 0
        return with_previous_year

    previous_year = _prepare_status_counts(previous_year_rows)[
        ["fachbereich", "studiengang", ACCEPTED_COLUMN]
    ].rename(columns={ACCEPTED_COLUMN: ACCEPTED_PREVIOUS_YEAR_COLUMN})
    merged = current_rows.merge(
        previous_year,
        on=["fachbereich", "studiengang"],
        how="left",
    )
    merged[ACCEPTED_PREVIOUS_YEAR_COLUMN] = (
        merged[ACCEPTED_PREVIOUS_YEAR_COLUMN].fillna(0).astype(int)
    )
    return merged


def _ordered_fachbereiche(rows: pd.DataFrame) -> list[str]:
    values = [str(value) for value in rows["fachbereich"].drop_duplicates().tolist()]
    ordered_known = [fachbereich for fachbereich in FACHBEREICH_ORDER if fachbereich in values]
    ordered_unknown = sorted(value for value in values if value not in FACHBEREICH_ORDER)
    return ordered_known + ordered_unknown


def _fachbereich_label(fachbereich: str) -> str:
    if fachbereich == "Gesundheit":
        return "Bereich Gesundheit"
    return f"Fachbereich {fachbereich}"


def _report_row(label: str, source: pd.Series, row_type: str) -> dict[str, object]:
    row = _base_report_row(label, row_type)
    for column in (
        PER_DATO_COLUMN,
        ACCEPTED_COLUMN,
        OPEN_COLUMN,
        NO_POTENTIAL_COLUMN,
        REJECTIONS_COLUMN,
    ):
        row[column] = int(source[column])
    if ACCEPTED_PREVIOUS_YEAR_COLUMN in source:
        _set_accepted_comparison(
            row,
            current_accepted=int(source[ACCEPTED_COLUMN]),
            previous_accepted=int(source[ACCEPTED_PREVIOUS_YEAR_COLUMN]),
        )
    return row


def _summary_row(label: str, source: pd.DataFrame, row_type: str) -> dict[str, object]:
    row = _base_report_row(label, row_type)
    for column in (
        PER_DATO_COLUMN,
        ACCEPTED_COLUMN,
        OPEN_COLUMN,
        NO_POTENTIAL_COLUMN,
        REJECTIONS_COLUMN,
    ):
        row[column] = int(source[column].sum())
    if ACCEPTED_PREVIOUS_YEAR_COLUMN in source:
        _set_accepted_comparison(
            row,
            current_accepted=int(source[ACCEPTED_COLUMN].sum()),
            previous_accepted=int(source[ACCEPTED_PREVIOUS_YEAR_COLUMN].sum()),
        )
    return row


def _set_accepted_comparison(
    row: dict[str, object], *, current_accepted: int, previous_accepted: int
) -> None:
    delta = current_accepted - previous_accepted
    row[ACCEPTED_PREVIOUS_YEAR_COLUMN] = previous_accepted
    row[ACCEPTED_DELTA_COLUMN] = delta
    if previous_accepted == 0:
        row[ACCEPTED_DELTA_PERCENT_COLUMN] = PLACEHOLDER_VALUE
    else:
        row[ACCEPTED_DELTA_PERCENT_COLUMN] = delta / previous_accepted * 100


def _base_report_row(label: str, row_type: str) -> dict[str, object]:
    row: dict[str, object] = {
        PROGRAM_COLUMN: label,
        ROW_TYPE_COLUMN: row_type,
    }
    for column in PLACEHOLDER_COLUMNS:
        row[column] = PLACEHOLDER_VALUE
    return row
