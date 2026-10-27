# myfitness – Implementierungsplan

Stand: 27.10.2026 · Rollen: Kunde = Nutzer, Umsetzung = Claude Code

## 1. Ziel

Ein persönliches Analysewerkzeug für die eigenen Garmin-Daten. Es soll Erkenntnisse liefern, die Garmin Connect nicht bietet, vor allem Zusammenhänge zwischen Laufmetriken sowie zwischen Erholung und Leistung.

- **Gewichtung:** 70 % Erkenntnis, 30 % Lernen (Python, Polars, Seaborn).
- **Nutzung:** wöchentlicher Blick, dazu anlassbezogene Exploration.
- **Trainingskontext:** allgemeine Fitness, gelegentliche Wettkämpfe zum Spaß.
- **Erfolgskriterium:** Der Nutzer hat mehr über Polars gelernt und eine Einsicht in sein Training gewonnen, die er vorher nicht hatte, z. B. einen Zusammenhang zwischen zwei Messgrößen.

### Leitfragen

1. Werde ich bei gleichem Puls schneller?
2. Wie wirken sich Schlaf und HRV auf meine Läufe aus?
3. Welche Zusammenhänge gibt es zwischen Pace, Herzfrequenz, Schrittfrequenz, Atemfrequenz, Schrittlänge und vertikalem Verhältnis, sowohl zwischen Läufen als auch innerhalb eines Laufs?

## 2. Rahmenbedingungen

| Thema | Festlegung |
|---|---|
| Geräte | Garmin Venu 4, Polar H10 (HF beim Laufen). Kein Gerätewechsel, ca. 1 Jahr Historie |
| Laufdynamik | Wird von der Uhr am Handgelenk berechnet. Trends sind aussagekräftig, absolute Werte nur eingeschränkt mit Brustgurt-Werten vergleichbar |
| Datenquelle | Garmin Connect **Personal API** (offiziell, read-only, pull) über Garmins Client `garmin-connect-personal-api-python` |
| API-Schlüssel | Wird vom Nutzer erzeugt (1 Jahr Gültigkeit), abgelegt in `~/.config/garmin/connect-personal-api-key` mit `chmod 600` |
| Wetter | Open-Meteo Historical Weather API (kostenlos, ohne Schlüssel) |
| Umgebung | macOS, VS Code (Notebooks), uv, Python ≥ 3.12 (Mindestversion des Garmin-Clients) |
| Umsetzung | Claude Code schreibt, der Nutzer arbeitet experimentell nach. Daraus folgt: lesbarer, nachvollziehbarer Code |
| Aktualisierung | Manuell, mit einem einzigen Befehl |
| Versionierung | Git, **keine Daten, keine Schlüssel, keine Notebook-Ausgaben** |
| Engineering | Bewusst schlank: keine Test-Suite, kein Linting. Nur Plausibilitätsprüfungen für die Kernformeln |
| Zeitrahmen | Erstes Ergebnis am Wochenende 31.10./01.11.2026 (Meilensteine M0–M3) |

## 3. Umfang

**Im Umfang**
- Laden aller Aktivitäten (inkl. FIT-Dateien) und Tageswerte, inkrementell
- Bereinigte Tabellen für Aktivitäten, Zeitreihen, Runden und Tageswerte
- Analysen zum Laufen; alle Sportarten fließen in die Belastungsmodelle ein
- Sportart als durchgängiger Filter, damit spätere Analysen anderer Sportarten möglich sind
- Kontextfaktoren: Temperatur, Höhenmeter, Gewicht
- Ruhepuls wird als **Ergebnisgröße** (Fitnessindikator) geführt, nicht als Einflussfaktor

**Nicht im Umfang (erste Ausbaustufe)**
- LLM-Auswertung
- Automatische Aktualisierung
- Dashboards und Web-Oberflächen
- Eigene Analysen für andere Sportarten (nur als Filter vorbereitet)

## 4. Annahmen (bestätigt 27.10.2026)

Diese Punkte hat der Product Owner vorgeschlagen. Der Kunde hat sie am 27.10.2026 bestätigt.

- **A1:** Die erste Analyse (M3) behandelt Effizienzfaktor und aerobe Entkopplung.
- **A2:** Der Korrelationsbaukasten entsteht nach der ersten Analyse (M4), nicht vorher.
- **A3:** Es gibt ein festes Wochen-Notebook (M6).
- **A4:** Die Liste „Nicht im Umfang“ ist vollständig.
- **A5:** Code, Bezeichner und Code-Kommentare sind auf Englisch; Notebook-Texte und Dokumentation auf Deutsch.
- **A6:** Kernformeln bekommen je eine Plausibilitätsprüfung (streichbar).

## 5. Architektur

```
Garmin Personal API ─┐
                     ├─► data/raw/        (unverändert: JSON, FIT-ZIP)
Open-Meteo ──────────┘        │
                              ▼  transform
                        data/processed/   (Parquet)
                              │
                              ▼
                        src/myfitness/    (Metriken, Exploration, Plots)
                              │
                              ▼
                        notebooks/        (Fragen, Erklärungen, Grafiken)
```

Die Rohschicht wird nur ergänzt, nie umgeschrieben. Ändert Garmin ein Antwortschema, muss nur die Transformation angepasst werden; ein erneuter Download ist nicht nötig.

### Verzeichnisstruktur

```
myfitness/
├── pyproject.toml
├── CLAUDE.md, PLAN.md, README.md
├── config.example.toml        # persönliche Parameter (Vorlage)
├── config.toml                # gitignored
├── src/myfitness/
│   ├── config.py              # Pfade, Parameter
│   ├── cli.py                 # `myfitness update | transform`
│   ├── ingest/
│   │   ├── garmin.py          # Personal API → data/raw/garmin
│   │   └── weather.py         # Open-Meteo → data/raw/weather
│   ├── transform/
│   │   ├── fit.py             # FIT-Dekodierung, Einheiten
│   │   ├── activities.py
│   │   ├── records.py
│   │   └── daily.py
│   ├── metrics.py             # EF, Entkopplung, TRIMP, CTL/ATL/TSB
│   ├── explore.py             # Korrelationsbaukasten
│   ├── plots.py
│   └── checks.py              # Plausibilitätsprüfungen
├── notebooks/
│   ├── 00_datencheck.ipynb
│   ├── 01_effizienz.ipynb
│   ├── 02_korrelationen.ipynb
│   ├── 03_belastung.ipynb
│   └── 04_woche.ipynb
└── data/                      # gitignored, Pfad über MYFITNESS_DATA_DIR änderbar
    ├── raw/garmin/{activities,fit,daily}/
    ├── raw/weather/
    └── processed/
```

## 6. Datenmodell (`data/processed`)

**Zeitregel:** Zeitpunkte werden in UTC gespeichert. Für die Zuordnung zu einem Tag zählt das lokale Datum. Schlaf gehört zum Garmin-`calendarDate`, also zum Tag des Aufwachens.

| Tabelle | Granularität | Schlüssel | Wichtige Spalten |
|---|---|---|---|
| `activities` | 1 Zeile pro Aktivität | `activity_id` | sport, sub_sport, activity_type, name, start_utc, start_local, duration_s (Timer-Zeit wie „Zeit“ in Connect), elapsed_s, moving_s, distance_m, avg_hr, max_hr, avg_speed_mps, elevation_gain_m, start_lat, start_lon, training_load, avg_cadence_spm, avg_respiration_rate, workout_rpe, workout_feel, temp_c, humidity_pct, wind_kmh |
| `records` | 1 Zeile pro Messpunkt (~1 s) | `activity_id`, `timestamp_utc` | elapsed_s, distance_m, speed_mps, heart_rate, cadence_spm, step_length_mm, vertical_oscillation_mm, vertical_ratio_pct, stance_time_ms, respiration_rate, power_w, altitude_m, lat, lon |
| `laps` | 1 Zeile pro Runde | `activity_id`, `lap_index` | start_utc, duration_s (Timer), elapsed_s, distance_m, avg_hr, avg_speed_mps, avg_cadence_spm |
| `daily` | 1 Zeile pro Tag | `date` | resting_hr, hrv_overnight_avg, hrv_status, sleep_duration_s, sleep_score, sleep_deep_s/light_s/rem_s/awake_s, body_battery_high/low, avg_stress, steps, weight_kg (gemessen), weight_kg_ffill (fortgeschrieben) |
| `activity_metrics` | 1 Zeile pro Aktivität | `activity_id` | trimp, trimp_source (alle Sportarten); ef, ef_moving_s, ef_first_half, ef_second_half, speed_cv, steady, decoupling_pct (nur Läufe) |
| `training_load` | 1 Zeile pro Tag | `date` | trimp, ctl, atl, tsb (alle Sportarten) |
| `hr_zones` | 1 Zeile pro Zone | `zone` | floor_bpm, ceiling_bpm, snapshot_date, max_hr_used |

Welche `records`-Spalten tatsächlich befüllt sind, entscheidet die Feldinventur (M1.7).

## 7. Meilensteine

### M0 – Projektgerüst (geht auch ohne API-Schlüssel)

- [x] 0.1 uv-Projekt im src-Layout anlegen, Python ≥ 3.12. Abhängigkeiten: `garmin-connect-personal-api-python`, `garmin-fit-sdk`, `polars`, `seaborn`, `matplotlib`, `requests`; dev: `ipykernel`, `nbstripout`
- [x] 0.2 `.gitignore` für `data/`, `config.toml`, `.venv/`, Schlüssel- und Token-Dateien. `nbstripout` als Git-Filter einrichten (`nbstripout --install`)
- [x] 0.3 `config.py` mit Datenpfad (`MYFITNESS_DATA_DIR`, Default `./data`) und persönlichen Parametern aus `config.toml` (u. a. `hr_max`, `sex` für TRIMP). Dazu eine `config.example.toml`
- [x] 0.4 CLI-Gerüst mit argparse: `uv run myfitness --help`
- [x] 0.5 Kurze `README.md` (Einrichtung, Befehle, Ablage des API-Schlüssels)

**Abnahme:** `uv sync` läuft fehlerfrei. `uv run myfitness --help` zeigt die Befehle. Ein Notebook mit Ausgaben erscheint in `git diff` ohne Ausgaben.

### M1 – Ingestion (Rohschicht)

- [x] 1.1 Authentifizierung über `resolve_api_key()` und `PersonalApiAuthenticator`. Fehlt der Schlüssel, eine verständliche Meldung mit Link zur Garmin-Einstellungsseite ausgeben
- [x] 1.2 Aktivitäten: Liste seitenweise laden (`search_activities`, `limit=50`), Details nach `raw/garmin/activities/{id}.json`, FIT-ZIP nach `raw/garmin/fit/{id}.zip`. Nur fehlende Aktivitäten laden
- [x] 1.3 Tageswerte in Zeitfenstern laden. Grenzen (extern ermittelt, Stand 22.10.2026):

  | Endpunkt (Wrapper) | max. Tage pro Aufruf |
  |---|---|
  | `get_daily_summaries` | 180 |
  | `get_daily_hrv_summaries` | 180 |
  | `get_daily_sleep_summaries` | 28 |
  | `get_daily_body_battery` | 28 |
  | `get_daily_stress` | 7 |
  | `get_daily_steps` | 7 |
  | `get_weight_measurements` | 28 funktioniert (getestet 27.10.2026, 15 Fenster ohne Fehler); höhere Werte nicht getestet |

  Ablage unter `raw/garmin/daily/{endpoint}/{start}_{end}.json`. Die letzten 3 Tage bei jedem Lauf neu laden, weil die Uhr nachsynchronisiert
- [x] 1.4 Robustheit: konfigurierbare Pause zwischen Requests (Default 1 s). Bei 429 oder 5xx exponentieller Backoff mit höchstens 3 Versuchen. Ein 400 wird mit Endpunkt und Fenster geloggt, der Lauf geht weiter. Fortschritt auf stderr ausgeben
- [x] 1.5 Den Ladestand aus den vorhandenen Dateien ableiten, keine separate Statusdatei. Das macht die Ingestion idempotent und fortsetzbar
- [x] 1.6 Befehl `uv run myfitness update [--since YYYY-MM-DD]`. Beim Erstlauf standardmäßig 400 Tage zurück
- [x] 1.7 **Prüfaufgabe Feldinventur** (`notebooks/00_datencheck.ipynb`): Für alle Lauf-FITs pro Record- und Session-Feld den Anteil befüllter Werte ermitteln. Ausdrücklich prüfen: Atemfrequenz (z. B. `enhanced_respiration_rate`), Laufdynamik (`step_length`, `vertical_oscillation`, `vertical_ratio`, `stance_time`), Temperatur sowie VO2max-bezogene Felder. Ergebnis in Abschnitt 10 dieses Plans eintragen

**Abnahme:** Der Erstlauf lädt das ganze Jahr. Ein zweiter Lauf direkt danach lädt nur die letzten Tage und keine FIT-Datei erneut. Ein abgebrochener Lauf setzt korrekt fort. Die Feldinventur ist dokumentiert.

### M2 – Transformation

- [x] 2.1 FIT-Dekodierung mit `garmin-fit-sdk` liefert Records, Laps und Session. Einheiten normalisieren (siehe CLAUDE.md, Abschnitt „FIT-Fallstricke“)
- [x] 2.2 `activities.parquet` aus Detail-JSON und FIT-Session aufbauen
- [x] 2.3 `daily.parquet` aus den Tagesendpunkten: eine Zeile pro Tag, Gewicht als Messwert und als fortgeschriebener Wert
- [x] 2.4 Wetter: Open-Meteo-Archiv, stündlich (`temperature_2m`, `relative_humidity_2m`, `wind_speed_10m`), für die Startkoordinaten. Zuordnung über die nächstgelegene Stunde. Cache unter `raw/weather/{activity_id}.json`. Aktivitäten ohne GPS (Laufband) bekommen `null`
- [x] 2.5 `myfitness update` ruft danach die Transformation auf; `myfitness transform` läuft auch einzeln

**Abnahme:** Alle Parquet-Dateien existieren. Bei einem Stichproben-Lauf stimmen Distanz, Dauer und Ø-HF mit Garmin Connect überein (±1 %). Die Kadenz liegt im plausiblen Bereich (ca. 150–190 spm).

**Ergebnis der Abnahme (27.10.2026):** Abgleich aller 154 Läufe in `00_datencheck.ipynb`. Distanz, Ø-HF und Zeitspanne der Records weichen höchstens 0,4 % von Garmins Zusammenfassung ab. Die Kadenz stimmt exakt mit Connect überein (Median der Laufmediane 157 spm). Sehr langsame Läufe (1,4–1,8 m/s) liegen echt bei 117–145 spm, das ist kein Umrechnungsfehler.

Entscheidungen in M2:
- Kadenz in spm nur für Fußsportarten (Laufen, Gehen, Wandern); bei anderen Sportarten `null`.
- In Connect zugeschnittene Aktivitäten (`trimmed`) behalten ihre Original-FIT. Deshalb werden die Records auf [Start, Start + `elapsed_s`] beschnitten (betrifft 1 Aktivität).
- Tageswerte: Ruhepuls und Body Battery stammen aus `daily_summaries`, Stress und Schritte aus den eigenen Endpunkten. Negative Garmin-Werte (Kennung für „fehlt“) werden zu `null`.
- Startkoordinaten gehen auf 2 Nachkommastellen gerundet (ca. 1 km) an Open-Meteo.

### M3 – Erste Analyse: Effizienz (Wochenendziel)

Definitionen:
- **Effizienzfaktor (EF)** = mittlere Geschwindigkeit [m/min] ÷ mittlere HF. Gerechnet über die bewegte Zeit nach 10 min Aufwärmen, nur für Läufe ab 30 min.
- **Aerobe Entkopplung** = (EF₁ − EF₂) ÷ EF₁ × 100. EF₁ und EF₂ sind die EFs der ersten und zweiten Hälfte der bewegten Zeit nach dem Aufwärmen. Nur für Läufe ab 45 min mit gleichmäßigem Tempo (Variationskoeffizient der Geschwindigkeit unter einer Schwelle, Startwert 0,15).
- **Bewegte Zeit** (bestätigt 27.10.2026): Messpunkte mit Geschwindigkeit ≥ 1,0 m/s. Aufwärmen und Mindestdauern zählen in bewegter Zeit. Mittelwerte sind zeitgewichtet (Gewicht = Sekunden seit dem vorigen Messpunkt, höchstens 5 s).

Aufgaben:
- [x] 3.1 `metrics.py`: `efficiency_factor()` und `aerobic_decoupling()`, Ergebnisse in `activity_metrics.parquet`
- [x] 3.2 `notebooks/01_effizienz.ipynb`: EF pro Lauf über das Jahr mit gleitendem 28-Tage-Mittel, eingefärbt nach Temperatur. Entkopplung der langen, gleichmäßigen Läufe über die Zeit
- [x] 3.3 Plausibilitätsprüfung in `checks.py` mit einer synthetischen Zeitreihe, deren Ergebnis bekannt ist

**Ergebnis (27.10.2026):** EF für 84 Läufe, Entkopplung für 16 von 19 langen Läufen. Der EF stieg von 0,83 (erste 3 Monate) auf 0,88 (letzte 3 Monate), also etwa +5 %. Der scheinbar positive Zusammenhang von EF und Temperatur (r = 0,29) verschwindet nach Abzug des 28-Tage-Trends (r = −0,04). Er entstand über die Jahreszeit. Hypothese: Läufe ab 22 °C liegen etwa 0,06 unter dem Trend (n = 5).

**Abnahme:** Das Notebook läuft von oben bis unten fehlerfrei. Markdown-Zellen erklären jeweils Frage, Methode und Grenzen der Aussage.

### M4 – Korrelationsbaukasten

- [x] 4.1 `explore.py`, Ebene **zwischen Läufen**: pro Lauf aggregierte Metriken plus Kontext (Wetter, Höhenmeter, Gewicht) plus Tageswerte der Vortage über `join_asof` bzw. Lags
- [x] 4.2 `explore.py`, Ebene **innerhalb eines Laufs**: Records, optional in 30-s-Fenster gebündelt (`group_by_dynamic`)
- [x] 4.3 Gemeinsame Filter: Sportart, Zeitraum, HF-Zone, Mindestdauer
- [x] 4.4 Ausgaben: Korrelationsmatrix (Pearson und Spearman) als Heatmap, Streudiagramm mit Regression, Lag-Analyse (Tageswert an t−1 und t−2 gegen Laufmetrik)
- [x] 4.5 `notebooks/02_korrelationen.ipynb`: Leitfrage 2 (Schlaf/HRV → Leistung) und freie Exploration der Laufmetriken aus Leitfrage 3. Atemfrequenz nur, wenn die Feldinventur sie bestätigt

**Hinweis für die Notebook-Texte:** n = 1, Störgrößen (Temperatur, Steigung, Ermüdung) und viele Tests auf einmal. Ergebnisse werden als Hypothesen formuliert, nicht als Belege.

**Abnahme:** Ein neues Variablenpaar lässt sich mit einer einzigen Notebook-Zelle untersuchen.

Festlegungen (bestätigt 27.10.2026):
- **Lags:** Lag k = Tageswert vom Laufdatum minus k Tage. Nachtwerte (Schlaf, HRV, Ruhepuls) ab Lag 0, also der Nacht direkt vor dem Lauf. Tageswerte (Stress, Schritte, Body Battery) erst ab Lag 1, weil der Lauftag den Lauf enthält.
- **HF-Zonen:** Garmins in Connect eingestellte Zonen über `get_heart_rate_zones`, datierter Schnappschuss unter `raw/garmin/heart_rate_zones/{datum}.json`, Tabelle `hr_zones.parquet`. Stand: Methode HR_MAX, HF_max 178, Untergrenzen 89/107/125/142/160.

**Ergebnis (27.10.2026), als Hypothesen:**
- **Vortag statt Nacht davor:** Die Erholungswerte des *Vortags* (Lag 1) hängen konsistent mit der Tagesform zusammen (`ef_vs_trend`, |ρ| 0,20–0,26). Die Nacht direkt vor dem Lauf (Lag 0) zeigt nichts. Mögliche Störgröße: ein Ruhetag am Vortag (mit M5 prüfen).
- **Schrittlänge statt Kadenz:** Die Schrittlänge hängt mit dem EF zusammen (ρ ≈ 0,59, in Zone 3 0,61), die Kadenz kaum.
- **Innerhalb eines Laufs:** Die Atemfrequenz folgt der HF (Median ρ 0,64). Mehr Tempo kommt aus Kadenz *und* Schrittlänge (0,83 bzw. 0,72).

### M5 – Belastungsmodell

- [x] 5.1 TRIMP nach Banister für alle Aktivitäten mit HF: Σ Δt[min] · HRr · k₁ · e^(k₂·HRr) mit HRr = (HF − HF_Ruhe) ÷ (HF_max − HF_Ruhe). k₁/k₂ geschlechtsabhängig aus `config.toml` (0,64/1,92 bzw. 0,86/1,67). HF_Ruhe kommt aus `daily`. Gibt es keine Records, wird mit Ø-HF × Dauer gerechnet; ohne HF ist TRIMP = 0 und die Aktivität wird gekennzeichnet
- [x] 5.2 Tägliche Reihe mit CTL (EWMA 42 Tage), ATL (7 Tage) und TSB = CTL − ATL des Vortags. Tage ohne Training zählen als 0
- [x] 5.3 `notebooks/03_belastung.ipynb` mit Filter nach Sportart
- [x] 5.4 Plausibilitätsprüfung für TRIMP und EWMA

**Abnahme:** Die Kurven passen zum Trainingsgefühl, und Ruhetage senken die ATL sichtbar.

Parameter (bestätigt 27.10.2026): HF_max = 183 (höchster gemessener Wert), TRIMP-Konstanten männlich (0,64/1,92), in `config.toml`.

Festlegungen in M5:
- TRIMP über die gesamte aufgezeichnete Zeit, Stehen eingeschlossen. Zeitgewicht pro Messpunkt höchstens 5 s.
- HRr auf [0, 1] begrenzt. Fehlt der Ruhepuls eines Tages, gilt der letzte bekannte (`join_asof`).
- CTL/ATL starten am Tag vor der ersten Aktivität bei 0 (Einschwingphase ca. 6 Wochen).

**Ergebnis (27.10.2026):**
- Alle 251 Aktivitäten haben HF-Records. Laufen trägt 85 % der Gesamtbelastung.
- Die ATL fällt an allen 199 Ruhetagen. Ob die Kurven zum Trainingsgefühl passen, beurteilt der Nutzer.
- Ruhetag-Hypothese aus M4 geprüft: Der Zusammenhang zwischen Vortags-Erholung und Tagesform besteht nach Ruhe- und nach Trainingstagen gleichermaßen. Der Ruhetag erklärt ihn also nicht.
- TSB sagt die Tagesform nicht vorher (ρ ≈ −0,17).

### M6 – Wochenblick

- [x] 6.1 `notebooks/04_woche.ipynb` mit einem Stichtag als Parameter: Wochenumfang (km, Zeit) je Sportart, CTL/ATL/TSB, EF-Trend, Schlaf, HRV, Ruhepuls und Gewicht der letzten 8 Wochen

**Abnahme:** Stichtag setzen, „Run All“ ausführen, und das Notebook läuft ohne weitere Eingriffe durch.

**Ergebnis (27.10.2026):** Logik in `week.py`, Grafiken in `plots.py`. Getestet mit Stichtag heute und 15.03.2026, beide laufen ohne Eingriff durch. Die Woche des Stichtags zählt nur bis zum Stichtag. Das Notebook zeigt an, wie viele Tage sie schon umfasst.

### M7 – Backlog (nicht priorisiert)

- Mean-Max-Kurve und Critical Speed
- Herzfrequenz-Erholung nach Intervallen
- Steigungsbereinigte Pace (GAP)
- Analysen weiterer Sportarten
- LLM-Unterstützung
- Automatische Aktualisierung

## 8. Lernpfad

| Meilenstein | Polars | Seaborn / Matplotlib |
|---|---|---|
| M2 | `read_json`/`json_normalize`, `unnest`, Datentypen, `dt.convert_time_zone`, `with_columns`, `write_parquet` | – |
| M3 | `filter`, `group_by().agg()`, `rolling_mean` / `group_by_dynamic` | `relplot`, `lineplot`, Farbskalen |
| M4 | `join_asof`, `shift` (Lags), Fensterfunktionen mit `over()`, `scan_parquet` (lazy) | `heatmap`, `lmplot`, `pairplot`, `FacetGrid` |
| M5 | `ewm_mean`, Datumsreihen erzeugen und auffüllen (`date_range` + Join, `upsample`) | Mehrachsen-Plots |

## 9. Risiken und offene Punkte

| Risiko | Umgang |
|---|---|
| Atemfrequenz mit H10 an der Venu 4 möglicherweise nicht vorhanden | Feldinventur (1.7) entscheidet, ob sie in M4 vorkommt |
| Garmin entfernt laut Berichten einige berechnete Felder (u. a. VO2max, Erholungszeit) aus API-FITs; ob das auch für Personal Keys gilt, ist unklar | Für die eigenen Metriken nicht kritisch. Die Feldinventur dokumentiert den Stand |
| Rate Limits sind nicht veröffentlicht | Drosselung und Backoff (1.4) |
| Fenstergrenzen der Endpunkte stammen aus externer Messung und können sich ändern | 400-Fehler werden geloggt, Grenzen zentral konfigurierbar |
| Antwortschemata können sich mit Connect-Releases ändern | Unveränderte Rohschicht, Swagger-Doku als Referenz |
| Das Open-Meteo-Archiv liegt einige Tage hinter dem aktuellen Datum | Fehlende Temperaturen werden beim nächsten Update nachgeladen |
| Laufdynamik wird am Handgelenk gemessen | Trends auswerten, absolute Werte nicht mit Brustgurt-Normen vergleichen |
| API-Schlüssel fehlt noch | M0 kann vorher umgesetzt werden |

## 10. Ergebnisse der Feldinventur

Stand 27.10.2026. Grundlage: 154 Läufe (`sport = running`) aus 251 Aktivitäten, 296 125 Records. Quelle: `notebooks/00_datencheck.ipynb`.

### Verfügbarkeit (Records)

| Feld | Anteil befüllter Werte | Anteil Läufe mit Werten | Folgerung |
|---|---|---|---|
| `heart_rate` | 99,8 % | 100 % | ✓ |
| `cadence` + `fractional_cadence` | 100 % | 100 % | ✓ |
| `enhanced_speed`, `enhanced_altitude`, `distance` | 100 % | 100 % | ✓ |
| `position_lat` / `position_long` | 99,3 % | 100 % | ✓ (Laufband-Läufe ohne GPS sind nicht dabei oder sehr selten) |
| `enhanced_respiration_rate` | 96,3 % | 96,8 % (149 von 154) | **Atemfrequenz ist vorhanden** und kommt in M4 vor |
| `step_length`, `vertical_ratio` | 97,8 % | 100 % | ✓ |
| `vertical_oscillation` | 98,1 % | 100 % | ✓ |
| `stance_time` | 75,2 % | 100 % | deutlich lückenhafter als die übrige Laufdynamik; Ursache offen |
| `stance_time_balance`, `stance_time_percent` | 1,2 % | 1,9 % | nicht verwendbar |
| `power` | 99,99 % | 100 % | Laufleistung vom Handgelenk, bisher nicht eingeplant |
| `temperature` | – | 0 % | **fehlt**; Temperatur kommt ausschließlich von Open-Meteo |

Daneben gibt es numerisch benannte Felder (z. B. `107`, `135`, `136`, `140`, `143`, `144`, `90`), die im öffentlichen FIT-Profil nicht beschrieben sind. Sie werden nicht verwendet.

### Session-Felder

- Vorhanden: `total_training_effect`, `total_anaerobic_training_effect`, `training_load_peak`, `avg_grade_adjusted_speed` (Garmins GAP, relevant für das Backlog), `enhanced_avg/min/max_respiration_rate` (96,8 %), `workout_rpe` und `workout_feel` (88 %), `total_timer_time` und `total_elapsed_time`.
- **Keine VO2max-Felder** und keine Erholungszeit unter einem bekannten Namen. Das passt zu den Berichten über entfernte Felder in API-FITs (Abschnitt 9).

### Einheiten (geprüft an einem Lauf)

| Thema | Befund | Folgerung für M2 |
|---|---|---|
| Koordinaten | Werte um 6,2 · 10⁸ → **Semicircles**, das SDK rechnet nicht um | Grad = Wert × 180 / 2³¹ |
| Kadenz | `cadence` Median 81, `fractional_cadence` 0 oder 0,5 → **pro Bein** | spm = 2 × (`cadence` + `fractional_cadence`) |
| `step_length` | Median 826 → mm | ✓ |
| `vertical_oscillation` | Median 79 → mm | ✓ |
| `stance_time` | Median 290 → ms | ✓ |
| `vertical_ratio` | Median 9,2 → % | ✓ |
| `enhanced_speed` | Median 2,25 → m/s | ✓ |
| `timestamp` | vom SDK als `datetime` mit Zeitzone UTC geliefert | ✓ |
| Pausen | `total_timer_time` < `total_elapsed_time` | bewegte Zeit über Timer-Events bzw. Lücken bestimmen |

## Quellen

- Garmin Personal API Client: https://github.com/garmin/connect-personal-api-python
- Personal API Swagger: https://developer.garmin.com/gc-developer-program/personal/swagger-docs/
- Endpunkt-Grenzen: https://shapecalendar.com/guides/garmin-personal-api
- Entfernte Felder in API-FITs: https://the5krunner.com/2026/10/22/garmin-personal-api/
- Open-Meteo Historical Weather API: https://open-meteo.com/en/docs/historical-weather-api
