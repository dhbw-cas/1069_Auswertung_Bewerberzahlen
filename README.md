# Auswertung Bewerberzahlen

Streamlit-Anwendung zur Bereinigung und historischen Auswertung von Bewerberzahlen.

## Aktueller Stand

- Phase 1: CSV-Upload, Bereinigung, Dublettenentscheidung, Statusableitung, Fachbereich-Zuordnung und Excel-Download.
- Phase 2: Bereinigte Daten koennen in PostgreSQL gespeichert werden.

## Lokal starten

```bash
uv run streamlit run src/app.py
```

## PostgreSQL konfigurieren

Die App liest die Datenbankverbindung aus `DATABASE_URL`.

```env
DATABASE_URL=postgresql://bewerberzahlen_app:<passwort>@<host>:5432/bewerberzahlen
```

Ohne `DATABASE_URL` funktioniert die Bereinigung weiter, aber das Speichern in die Datenbank ist deaktiviert.

## Sliplane

Die produktive Zielarchitektur ist:

- Streamlit-App als privater HTTP-Service.
- PostgreSQL als privater TCP-Service mit persistentem Volume.
- Basic-Auth-Proxy als oeffentlicher HTTP-Service vor der App.

PostgreSQL-Einrichtung: [`docs/sliplane-postgres.md`](docs/sliplane-postgres.md)

## Qualitaetschecks

```bash
uv run ruff check .
uv run ruff format .
uv run mypy .
uv run pytest
```
