# myfitness

Persönliche Analyse eigener Garmin-Daten mit Schwerpunkt Laufen. Plan und Meilensteine: [PLAN.md](PLAN.md).

## Einrichtung

```bash
uv sync                                   # Umgebung herstellen
cp config.example.toml config.toml        # persönliche Parameter eintragen
```

### API-Schlüssel

1. Schlüssel in Garmin Connect erzeugen: <https://connect.garmin.com/app/settings/personalApiToken> (1 Jahr gültig).
2. Ablegen und schützen:

   ```bash
   mkdir -p ~/.config/garmin
   pbpaste > ~/.config/garmin/connect-personal-api-key
   chmod 600 ~/.config/garmin/connect-personal-api-key
   ```

   Alternativ die Umgebungsvariable `GARMIN_PERSONAL_API_KEY` setzen.

Der daraus abgeleitete Bearer-Token wird vom Garmin-Client in `~/.config/garmin/connect-personal-api-bearer-token.json` (Rechte 0600) zwischengespeichert.

## Befehle

```bash
uv run myfitness update                    # neue Daten laden + transformieren
uv run myfitness update --since 2026-01-01 # ab einem Datum (erneut) laden
uv run myfitness transform                 # nur transformieren
uv run python -m myfitness.checks          # Plausibilitätsprüfungen
```

Der Erstlauf lädt 400 Tage und dauert wegen der Drosselung (1 s pro Aufruf) einige Minuten. Ein abgebrochener Lauf setzt beim nächsten Aufruf fort.

## Notebooks

| Notebook | Inhalt |
|---|---|
| `00_datencheck` | Feldinventur der FIT-Dateien, Abgleich der Transformation mit Garmin Connect |
| `01_effizienz` | Effizienzfaktor und aerobe Entkopplung (Leitfrage 1) |
| `02_korrelationen` | Schlaf/HRV und Leistung, Zusammenhänge der Laufmetriken (Leitfragen 2 und 3) |
| `03_belastung` | TRIMP, CTL, ATL, TSB |
| `04_woche` | Wochenblick: Stichtag setzen, „Run All“ |

**Jede Woche:** `uv run myfitness update`, dann `notebooks/04_woche.ipynb` mit „Run All“ ausführen. Die Notebooks laufen in VS Code mit dem Kernel aus `.venv`.

## Daten

- `data/` (änderbar über `MYFITNESS_DATA_DIR`) ist gitignored.
- `data/raw/` wird nur ergänzt, nie umgeschrieben. `data/processed/` enthält die Parquet-Tabellen.
- Notebook-Ausgaben werden durch `nbstripout` vor dem Commit entfernt. Nach einem frischen Klon einmal `uv run nbstripout --install` ausführen.
