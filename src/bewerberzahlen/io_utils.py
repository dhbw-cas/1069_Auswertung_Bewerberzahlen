from __future__ import annotations

from io import BytesIO

import pandas as pd

from .constants import ACCEPTED_COLUMN, FACHBEREICH_COLUMN, NO_POTENTIAL_COLUMN, REJECTION_COLUMN

CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin1")

IMPORT_COLUMN_RENAMES = {
    "Formular_Start_Datum": "BEW-Start",
    "Formular_Akzeptiert_Datum": ACCEPTED_COLUMN,
    "Formularfelder_Abgesagt_am": REJECTION_COLUMN,
    "Formularfelder_Kein_Potential": NO_POTENTIAL_COLUMN,
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
            return _normalize_import_columns(df)
        except UnicodeDecodeError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise ValueError("CSV-Datei konnte nicht gelesen werden.")


def _normalize_import_columns(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.rename(columns=IMPORT_COLUMN_RENAMES).copy()
    if FACHBEREICH_COLUMN not in normalized.columns:
        normalized[FACHBEREICH_COLUMN] = ""
    return normalized


def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)
    return buffer.getvalue()
