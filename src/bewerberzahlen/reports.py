from __future__ import annotations

from dataclasses import dataclass
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

PLACEHOLDER_COLUMNS = [
    "Akzeptiert VJ per dato",
    "Akzeptiert Δ",
    "Akzeptiert Δ %",
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


def build_bewerbungszahlen_wise_report(dashboard_rows: pd.DataFrame) -> pd.DataFrame:
    if dashboard_rows.empty:
        return pd.DataFrame(columns=REPORT_COLUMNS)

    rows: list[dict[str, object]] = []
    prepared = _prepare_status_counts(dashboard_rows)
    for fachbereich in _ordered_fachbereiche(prepared):
        fachbereich_rows = prepared[prepared["fachbereich"] == fachbereich].copy()
        sorted_rows = fachbereich_rows.sort_values(by="studiengang")
        for _, row in sorted_rows.iterrows():
            rows.append(_report_row(str(row["studiengang"]), row, "Studiengang"))
        rows.append(_summary_row(_fachbereich_label(fachbereich), fachbereich_rows, "Fachbereich"))

    rows.append(_summary_row("Gesamtsumme", prepared, "Gesamtsumme"))
    return pd.DataFrame(rows, columns=REPORT_COLUMNS)


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
    return row


def _base_report_row(label: str, row_type: str) -> dict[str, object]:
    row: dict[str, object] = {
        PROGRAM_COLUMN: label,
        ROW_TYPE_COLUMN: row_type,
    }
    for column in PLACEHOLDER_COLUMNS:
        row[column] = PLACEHOLDER_VALUE
    return row
