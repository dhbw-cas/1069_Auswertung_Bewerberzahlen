from __future__ import annotations

from io import BytesIO

import pandas as pd

from .constants import (
    ACCEPTED_COLUMN,
    FACHBEREICH_COLUMN,
    NO_POTENTIAL_COLUMN,
    PII_COLUMNS,
    PROGRAM_COLUMN,
    REJECTION_COLUMN,
    STATUS_COLUMN,
)

CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin1")
CLEANED_IMPORT_REQUIRED_COLUMNS = (STATUS_COLUMN, FACHBEREICH_COLUMN, PROGRAM_COLUMN)

IMPORT_COLUMN_RENAMES = {
    "Formular_Start_Datum": "BEW-Start",
    "Start": "BEW-Start",
    "Start_Datum": "BEW-Start",
    "Formular_Akzeptiert_Datum": ACCEPTED_COLUMN,
    "Akzeptiert_Datum": ACCEPTED_COLUMN,
    "Formularfelder_Abgesagt_am": REJECTION_COLUMN,
    "Abgesagt_am": REJECTION_COLUMN,
    "Formularfelder_Kein_Potential": NO_POTENTIAL_COLUMN,
    "Kein Potential": NO_POTENTIAL_COLUMN,
    "Kein_Potential": NO_POTENTIAL_COLUMN,
    "FB": FACHBEREICH_COLUMN,
}


def read_import_csv_from_bytes(content: bytes) -> pd.DataFrame:
    last_error: UnicodeDecodeError | None = None
    for encoding in CSV_ENCODINGS:
        try:
            df = pd.read_csv(
                BytesIO(content),
                sep=";",
                encoding=encoding,
                dtype=str,
                keep_default_na=False,
            )
            return normalize_import_dataframe(df)
        except UnicodeDecodeError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise ValueError("CSV-Datei konnte nicht gelesen werden.")


def read_cleaned_dataframe_from_bytes(content: bytes, filename: str) -> pd.DataFrame:
    """Read a manually edited cleaned XLSX export and reject unsafe columns."""
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("Bitte eine bearbeitete bereinigte XLSX-Datei hochladen.")

    df = pd.read_excel(BytesIO(content), dtype=str, keep_default_na=False)
    df = _normalize_cleaned_columns(df)
    _validate_cleaned_dataframe(df)
    return df


def normalize_import_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw import headers shared by current and historical exports."""
    normalized = df.copy()
    normalized.columns = [str(column).strip() for column in normalized.columns]
    normalized = normalized.rename(columns=IMPORT_COLUMN_RENAMES)
    duplicate_columns = normalized.columns[normalized.columns.duplicated()].tolist()
    if duplicate_columns:
        duplicate_labels = ", ".join(sorted({str(column) for column in duplicate_columns}))
        raise ValueError(f"Spalten sind nach der Normalisierung doppelt: {duplicate_labels}")
    if FACHBEREICH_COLUMN not in normalized.columns:
        normalized[FACHBEREICH_COLUMN] = ""
    return normalized.fillna("")


def _normalize_cleaned_columns(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = [str(column).strip() for column in normalized.columns]
    return normalized.fillna("")


def _validate_cleaned_dataframe(df: pd.DataFrame) -> None:
    if df.empty:
        raise ValueError("Die bearbeitete bereinigte Datei enthält keine Datenzeilen.")

    missing_columns = [column for column in CLEANED_IMPORT_REQUIRED_COLUMNS if column not in df]
    if missing_columns:
        raise ValueError(
            "Erforderliche Spalten fehlen in der bearbeiteten bereinigten Datei: "
            + ", ".join(missing_columns)
        )

    pii_columns = [column for column in PII_COLUMNS if column in df]
    if pii_columns:
        raise ValueError(
            "Die bearbeitete bereinigte Datei enthält personenbezogene Spalten: "
            + ", ".join(pii_columns)
        )


def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)
    return buffer.getvalue()
