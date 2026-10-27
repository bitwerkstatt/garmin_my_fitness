# CLAUDE.md – myfitness

Persönliche Analyse eigener Garmin-Daten mit Schwerpunkt Laufen. Der Plan steht in `PLAN.md`.

## Arbeitsweise

- Meilensteine aus `PLAN.md` in Reihenfolge abarbeiten und erledigte Aufgaben dort abhaken (`- [x]`).
- Bei Unklarheiten, besonders zu Metrikdefinitionen, nachfragen statt raten. Annahmen unter „Annahmen“ in `PLAN.md` gelten erst nach Bestätigung als fest.
- Nach jedem Meilenstein kurz zusammenfassen: was gebaut wurde und welche Polars-Konzepte darin vorkommen. Der Nutzer lernt am Code.

## Befehle

```bash
uv sync                          # Umgebung herstellen
uv add <paket>                   # Abhängigkeit hinzufügen (nie pip)
uv run myfitness update          # neue Daten laden + transformieren
uv run myfitness transform       # nur transformieren
uv run python -m myfitness.checks  # Plausibilitätsprüfungen
```

Notebooks laufen in VS Code mit dem Kernel aus `.venv`.

## Code-Konventionen

- Python ≥ 3.12, Paketmanagement ausschließlich mit uv.
- **Polars** für alle Datenverarbeitung. pandas nur, wenn eine Plot-Bibliothek es zwingend verlangt, und dann erst an dieser Stelle mit `.to_pandas()`.
- Seaborn und Matplotlib für Grafiken.
- **Lesbarkeit vor Kürze:** Ausdrücke in benannten Zwischenschritten statt verschachtelter Einzeiler. Bei nicht offensichtlichen Polars-Konstrukten (`join_asof`, `group_by_dynamic`, `over`, lazy) erklärt ein kurzer Kommentar, was passiert.
- Die Logik liegt in `src/myfitness/`. Notebooks rufen nur Funktionen auf, explorieren und erklären.
- Bezeichner und Code-Kommentare auf Englisch, Notebook-Texte und Doku auf Deutsch.
- Bewusst schlank: keine Test-Suite, kein Linting-Setup. Ausnahme: Für jede Formel in `metrics.py` gibt es eine Plausibilitätsprüfung in `checks.py`.
- Neue Abhängigkeiten nur mit Begründung. Vorgesehen sind: `garmin-connect-personal-api-python`, `garmin-fit-sdk`, `polars`, `seaborn`, `matplotlib`, `requests`, dev: `ipykernel`, `nbstripout`.

## Daten und Datenschutz (verbindlich)

- **Nie committen:** Daten, API-Schlüssel, Bearer-Tokens, `config.toml`, Notebook-Ausgaben. `data/` ist gitignored, `nbstripout` ist als Git-Filter aktiv.
- Den API-Schlüssel nur aus `~/.config/garmin/connect-personal-api-key` oder `GARMIN_PERSONAL_API_KEY` lesen. Ihn nie ausgeben oder loggen.
- `data/raw/` ist unveränderlich: Dateien werden nur hinzugefügt. Einzige Ausnahme ist das bewusste Nachladen der letzten Tage.
- Daten gehen nur an Garmin (Abruf) und Open-Meteo (nur Koordinaten und Zeit). An keine weiteren externen Dienste.

## Garmin Personal API

- Ausschließlich die offizielle Personal API über `garmin_personal_api` (`PersonalApiAuthenticator`, `GarminPersonalApiClient`). **Keine** inoffiziellen Bibliotheken wie `garth` oder `garminconnect`.
- Die API ist read-only und pull-basiert. Für Endpunkte ohne Wrapper gibt es `client.get(path, params=...)`. Referenz: https://developer.garmin.com/gc-developer-program/personal/swagger-docs/
- Tagesendpunkte haben Obergrenzen für den Zeitraum pro Aufruf (siehe `PLAN.md` 1.3). Die Grenzen zentral konfigurierbar halten.
- Drosseln (Default 1 s Pause). Bei 429/5xx Backoff, bei 400 loggen und weitermachen.
- `download_activity()` liefert ZIP-Bytes. Die ZIP-Datei unverändert in der Rohschicht ablegen und erst bei der Transformation entpacken.

## FIT-Fallstricke (beim Dekodieren prüfen, nicht blind übernehmen)

- **Kadenz:** Bei Läufen ist `cadence` im Record pro Bein angegeben. Schritte pro Minute = 2 × (`cadence` + `fractional_cadence`).
- **Koordinaten:** im Rohformat Semicircles, umgerechnet in Grad = Wert × 180 / 2³¹. Prüfen, ob `garmin-fit-sdk` das schon erledigt.
- **Einheiten:** `step_length` und `vertical_oscillation` in mm, `stance_time` in ms, `vertical_ratio` in %. Bei Geschwindigkeit und Höhe die `enhanced_*`-Felder bevorzugen.
- **Zeit:** FIT-Zeitstempel sind UTC.
- **Atemfrequenz:** steht, falls vorhanden, eventuell in `enhanced_respiration_rate`. Verfügbarkeit laut Feldinventur (`PLAN.md`, Abschnitt 10).
- **Pausen:** Lücken in den Zeitstempeln bzw. Timer-Events. Metriken werden über die bewegte Zeit gerechnet.
