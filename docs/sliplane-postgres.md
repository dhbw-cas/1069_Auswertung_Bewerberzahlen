# Sliplane PostgreSQL einrichten

Diese Anleitung beschreibt die produktive Datenbank fuer Phase 2.

## Zielbild

- PostgreSQL laeuft als privater Sliplane-Service.
- Die Streamlit-App greift ueber `DATABASE_URL` auf PostgreSQL zu.
- PostgreSQL ist nicht direkt aus dem Internet erreichbar.
- Persistente Daten liegen in einem Sliplane-Volume.

## PostgreSQL-Service anlegen

1. In Sliplane das passende Projekt oeffnen.
2. `Deploy Service` waehlen.
3. Als Deploy Source ein vorkonfiguriertes Docker-Hub-Image fuer PostgreSQL waehlen.
4. Einen expliziten PostgreSQL-Tag verwenden, nicht `latest`, z. B. `docker.io/library/postgres:16.2`.
5. Service-Name: `bewerberzahlen-postgres`.
6. `Expose Service` deaktivieren, damit die DB privat bleibt.
7. Netzwerk-Protokoll: `TCP`.
8. Port: `5432`.
9. Ein Volume anhaengen.
10. Mount Path fuer das Volume: `/var/lib/postgresql/data`.

## Environment Variables fuer PostgreSQL

Im PostgreSQL-Service setzen:

```env
POSTGRES_DB=bewerberzahlen
POSTGRES_USER=bewerberzahlen_app
POSTGRES_PASSWORD=<starkes-passwort>
```

`POSTGRES_PASSWORD` in Sliplane als Secret markieren.

## Internal Host ermitteln

Nach dem Deploy im PostgreSQL-Service unter `Service Settings` den internen Host bzw. die interne TCP-Adresse kopieren. Private Services koennen laut Sliplane-Doku von anderen Services auf demselben Server ueber diesen internen Host erreicht werden.

Die Adresse kann je nach Sliplane-Anzeige Host und Port getrennt oder bereits kombiniert enthalten. Fuer die App brauchen wir daraus eine PostgreSQL-URL:

```env
DATABASE_URL=postgresql://bewerberzahlen_app:<starkes-passwort>@<internal-host>:5432/bewerberzahlen
```

Wenn Sliplane den Port bereits in der internen Adresse anzeigt, den Port nicht doppelt eintragen.

## Streamlit-Service konfigurieren

Im Streamlit-Service die Environment Variable setzen:

```env
DATABASE_URL=postgresql://bewerberzahlen_app:<starkes-passwort>@<internal-host>:5432/bewerberzahlen
IMPORT_DELETE_PASSWORD=<starkes-loesch-passwort>
```

`DATABASE_URL` und `IMPORT_DELETE_PASSWORD` als Secrets markieren.

Die App legt die Tabellen beim ersten Speichern eines bereinigten Imports automatisch an.
Das Loeschen gespeicherter Importe ist nur verfuegbar, wenn `IMPORT_DELETE_PASSWORD` gesetzt ist.

## Erwartetes Schema

Die App erstellt automatisch:

- `import_batches`: ein Datensatz pro gespeicherten Import.
- `applications`: bereinigte Bewerbungszeilen pro Import.

Doppelte Importe werden ueber `import_batches.content_hash` verhindert. Der Hash basiert auf dem bereinigten Datenbestand, nicht auf dem Rohdateinamen.

## Lokale Entwicklung

Fuer lokale Tests entweder eine lokale PostgreSQL-Instanz verwenden oder eine separate Entwicklungsdatenbank bereitstellen.

Beispiel fuer eine lokale URL:

```env
DATABASE_URL=postgresql://bewerberzahlen_app:<passwort>@localhost:5432/bewerberzahlen
```

Die Sliplane-Produktivdatenbank sollte fuer lokale Entwicklung nicht oeffentlich exponiert werden.
