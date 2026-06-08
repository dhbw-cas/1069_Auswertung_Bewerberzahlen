# Auswertung Bewerberzahlen

Streamlit-Anwendung zur Bereinigung und historischen Auswertung von Bewerberzahlen.

## Aktueller Stand

- Phase 1: CSV-Upload, Bereinigung, Dublettenentscheidung, Statusableitung, Fachbereich-Zuordnung und Excel-Download.
- Phase 2: Bereinigte Daten können in PostgreSQL gespeichert werden.

## Lokal starten

```bash
uv run streamlit run src/app.py
```

## PostgreSQL konfigurieren

Die App liest die Datenbankverbindung aus `DATABASE_URL`.

```env
DATABASE_URL=postgresql://bewerberzahlen_app:<passwort>@<host>:5432/bewerberzahlen
IMPORT_DELETE_PASSWORD=<lösch-passwort>
```

Ohne `DATABASE_URL` funktioniert die Bereinigung weiter, aber das Speichern in die Datenbank ist deaktiviert.
Ohne `IMPORT_DELETE_PASSWORD` ist das Löschen gespeicherter Importe deaktiviert.

## Sliplane

Die produktive Zielarchitektur ist:

- Streamlit-App als privater HTTP-Service.
- PostgreSQL als privater TCP-Service mit persistentem Volume.
- Basic-Auth-Proxy als öffentlicher HTTP-Service vor der App.

Der Streamlit-Service nutzt den `Dockerfile` im Repository. In Sliplane ist daher kein Override CMD nötig.
`DATABASE_URL` und `IMPORT_DELETE_PASSWORD` sollten in Sliplane als Secrets gesetzt werden.
Der Docker-Start kann über `STREAMLIT_ENTRYPOINT` gesteuert werden: `src/app.py` für die Admin-App und `src/dashboard_app.py` für die Dashboard-only-App.

PostgreSQL-Einrichtung: [`docs/sliplane-postgres.md`](docs/sliplane-postgres.md)

## Qualitaetschecks

```bash
uv run ruff check .
uv run ruff format .
uv run mypy .
uv run pytest
```
