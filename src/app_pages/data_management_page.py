from __future__ import annotations

import pandas as pd
import streamlit as st

from bewerberzahlen.app_config import get_config_value, get_database_url
from bewerberzahlen.storage import (
    connection_from_url,
    delete_import_batch,
    is_delete_password_valid,
    list_import_batches,
)


def render_data_management_page() -> None:
    st.title("Datenstandverwaltung")
    database_url = get_database_url()
    if database_url is None:
        st.info("Keine Datenbankverbindung konfiguriert. Datenstandverwaltung ist deaktiviert.")
        return

    try:
        with connection_from_url(database_url) as conn:
            imports = list_import_batches(conn)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Import-Historie konnte nicht geladen werden: {exc}")
        return

    if not imports:
        st.info("Noch keine gespeicherten Importe vorhanden.")
        return

    import_rows = [
        {
            "ID": batch.id,
            "Snapshot-Datum": batch.snapshot_date.strftime("%d.%m.%Y"),
            "Datei": batch.filename,
            "Importiert von": batch.imported_by,
            "Importiert am": batch.created_at.strftime("%d.%m.%Y %H:%M"),
            "Zeilen": batch.row_count,
        }
        for batch in imports
    ]
    st.dataframe(pd.DataFrame(import_rows), hide_index=True, use_container_width=True)

    delete_password = get_config_value("IMPORT_DELETE_PASSWORD")
    if delete_password is None:
        st.warning(
            "Löschen ist deaktiviert. Bitte IMPORT_DELETE_PASSWORD als Secret setzen, "
            "wenn Importe löschbar sein sollen."
        )
        return

    with st.expander("Import löschen"):
        labels_by_id = {
            batch.id: (
                f"#{batch.id} | {batch.snapshot_date:%d.%m.%Y} | "
                f"{batch.filename} | {batch.row_count} Zeilen"
            )
            for batch in imports
        }
        with st.form("delete_import_form"):
            selected_id = st.selectbox(
                "Zu löschender Import",
                options=list(labels_by_id.keys()),
                format_func=lambda batch_id: labels_by_id[int(batch_id)],
            )
            entered_password = st.text_input("Lösch-Passwort", type="password")
            confirmed = st.checkbox("Ich möchte diesen Import dauerhaft löschen.")
            submit_delete = st.form_submit_button("Import löschen")

        if submit_delete:
            if not confirmed:
                st.error("Bitte das Löschen explizit bestätigen.")
                return
            if not is_delete_password_valid(entered_password, delete_password):
                st.error("Lösch-Passwort ist falsch.")
                return
            try:
                with connection_from_url(database_url) as conn:
                    deleted = delete_import_batch(conn, int(selected_id))
            except Exception as exc:  # noqa: BLE001
                st.error(f"Import konnte nicht gelöscht werden: {exc}")
                return
            if deleted:
                st.success("Import wurde gelöscht.")
                st.rerun()
            else:
                st.warning("Import wurde nicht gefunden oder war bereits gelöscht.")


render_data_management_page()
