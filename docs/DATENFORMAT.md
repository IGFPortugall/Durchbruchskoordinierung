# Datenformat (Schema 1)

Verbindlich für alle Clients: pyRevit-Extension, Web-App, Berichte.
Referenz-Implementierung: [`src/dbk_core`](../src/dbk_core) (Python 2.7 / 3.x).

## Projektordner

```
<Projektordner>/
├── projekt.json
├── pruefsets/<Firma>.json
├── modelle/<Modell>/<Hash>.frag   + <Hash>.json
├── plaene/<Firma>/<Geschoss>_<Name>.svg   + .json
└── ereignisse/<Firma>/<Zeit>_<Seq>_<Id8>.json
```

Dateien unter `modelle/` und `plaene/` werden nie überschrieben; eine neue Version bekommt
einen neuen Namen (Hash der Quelldatei).

- `<Firma>`: Firmenname, alles außer Buchstaben, Ziffern, `-`, `_` wird zu `_`.
- Jede Firma schreibt **nur** in `ereignisse/<eigene Firma>/`. Dateien werden nie geändert.
- Schreiben: zuerst `<name>.json.tmp`, dann umbenennen.
- Lesen: `.tmp` ignorieren; nicht lesbare JSON-Dateien überspringen und später erneut versuchen;
  Ereignisse, deren `firma` nicht zum Ordner passt, verwerfen.

## Ereignis

```json
{
  "schema": 1,
  "id": "9f0c1a2b4e5d4c8f9a0b1c2d3e4f5a6b",
  "zeit": "2026-11-24T10:20:11.123Z",
  "seq": 17,
  "firma": "IGF",
  "name": "M. Muster",
  "rolle": "TGA",
  "art": "status",
  "objekt": "HLS:4f1c2e3d-...-0004a2b1",
  "daten": { "wert": "abgelehnt", "geometrie_hash": "a1b2c3d4e5f60718", "kommentar": "Zu nah an der Stütze" }
}
```

| Feld | Bedeutung |
|---|---|
| `zeit` | UTC, ISO 8601 mit Millisekunden |
| `seq` | fortlaufend je Firma, ab 1 |
| `objekt` | Prüfobjekt-ID, empfohlen `<Modellkürzel>:<Revit UniqueId>`; `null` bei `pruefrunde_gestartet` |

**Reihenfolge** aller Ereignisse: nach `zeit`, dann `firma`, dann `seq`.

### Arten

| `art` | `daten` | Wer |
|---|---|---|
| `pruefrunde_gestartet` | `{"runde", "name", "frist"}` | Ersteller |
| `eingereicht` | `{"objekt": Objektdaten, "runde", "stand"}` – `stand` = Name des Durchbruch-Stands (optional) | Besitzer (erste einreichende Firma) |
| `geaendert` | `{"objekt": Objektdaten}` | Besitzer |
| `geloescht` | `{}` | Besitzer |
| `status` | `{"wert", "geometrie_hash", "kommentar", "kontext"}` | jede Rolle |
| `nachricht` | `{"text"}` | jede Rolle |
| `modell_veroeffentlicht` | `{"modell", "datei", "hash", "format", "name", "quelle", "stand", "ebenen", "info", "revit_version", "plan"}` – `format` `fbx`/`ifc`/`frag`, bei 2D-Plänen `png` mit `plan` = `{"art": "grundriss"\|"schnitt", "ecken_mm": [4 × [x, y, z]] (unten links, unten rechts, oben rechts, oben links), "ebene", "massstab", "pixel"}` | Besitzer des Modells (erste veröffentlichende Firma) |
| `modell_ausrichtung` | `{"modell", "x_mm", "y_mm", "z_mm", "drehung_grad"}` – Verschiebung (Revit-Achsen) und Drehung um die senkrechte Achse durch die Modellmitte | nur Besitzer des Modells; alle anderen richten nur lokal im Browser aus |
| `stand_eingereicht` | `{"stand", "runde", "mitglieder": [Objekt-IDs], "objekte": {Objekt-ID: Objektdaten}}` – Momentaufnahme eines Stands, siehe unten | einreichende Firma |
| `stand_zurueckgezogen` | `{"stand"}` – alle Objekte der Firma in diesem Stand fallen heraus, ihre Entscheidungen verfallen | einreichende Firma |
| `modell_entfernt` | `{"modell"}` – Modell verschwindet für alle; eine neue Veröffentlichung beginnt von vorn (neuer Besitzer möglich) | nur Besitzer des Modells |

**Stand als Momentaufnahme** (`stand_eingereicht`, ein Ereignis je Einreichung, `objekt` = `null`):

- `mitglieder`: alle Objekte, die jetzt zum Stand gehören (in Revit: in der 3D-Ansicht des Stands sichtbar).
- `objekte`: Objektdaten nur für neue und geänderte Objekte. Gleicher `geometrie_hash` wie bisher =
  reiner Datenabgleich (zählt nicht als erneute Einreichung, Entscheidungen bleiben gültig).
- Mitglieder ohne Eintrag in `objekte` werden als „unverändert“ bestätigt (nur bestehende Objekte der Firma).
- Objekte der Firma, die bisher zu diesem Stand gehörten und in `mitglieder` fehlen, fallen heraus.
- Je Objekt wird `einreichung` = `neu` / `geaendert` / `unveraendert` aus der letzten Momentaufnahme gemerkt.
- `stand` = `""` steht für „ohne Stand“.

`kontext` (optional) im Status: Modellversionen, gegen die geprüft wurde, z. B.
`{"ARC": "3f9a1c7e2b4d6a80", "TWP": "c01d..."}`.

Bei `modell_veroeffentlicht` ist `objekt` = `null`. Aktuelle Version eines Modells = letzte
Veröffentlichung seines Besitzers.

### Objektdaten

Pflicht ist nur `geometrie_hash`. Empfohlen:

```json
{
  "nummer": "TGA-2_OG01-0042",
  "kategorie": "Allgemeines Modell", "familie": "IGF_Durchbruch_Rechteck", "typ": "Wand",
  "ebene": "2_OG01",
  "revit_unique_id": "...", "ifc_guid": "...", "modell": "HLS",
  "geometrie": { "min": [x, y, z], "max": [x, y, z], "form": "rechteck",
                 "masse": { "breite": 400, "hoehe": 300, "tiefe": 250 } },
  "lage": "wand",
  "uk_mm": 240, "ok_mm": 540,
  "masse_quelle": { "breite": "Gesamt Breite", "hoehe": "Gesamt Höhe", "tiefe": "Gesamt Tiefe" },
  "ausrichtung": { "mitte_mm": [x, y, z], "achsen": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "groesse_mm": [400, 250, 300] },
  "revit_modell": "Beispiel-TGA",
  "flaeche_m2": 0.12,
  "wirt": { "kategorie": "Wände", "tragend": true, "brandwand": false },
  "gewerke": ["Lüftung"]
}
```

Koordinaten und Maße in **mm**, Projektkoordinaten.

- `min`/`max`: Box der **Volumenkörper** der Familie (Symbol- und Modelllinien zählen nicht).
- `lage`: `wand` (waagerechter Durchbruch, Maße `breite` × `hoehe`) oder `decke`
  (senkrecht, `breite` × `laenge`); rund: `durchmesser`. `tiefe` = Bauteildicke.
- Maße aus Revit-Parametern, zuerst `Gesamt Breite/Höhe/Länge/Tiefe`, dann `Breite/Höhe/…`,
  sonst aus der Box. Eigene Namen im Prüfset: `"masse_parameter": {"breite": ["Öffnung B"]}`.
  `masse_quelle` hält fest, welcher Parameter genommen wurde.
- `uk_mm`/`ok_mm`: Unter-/Oberkante bezogen auf die Ebene (`ebene`).
- `ausrichtung` (optional, nur Darstellung, nicht im Hash): gedrehte Box der Volumenkörper im
  Koordinatensystem des Exemplars – Mitte, drei Achsen (Einheitsvektoren in Projektkoordinaten) und
  Größe je Achse. Damit zeigt der Viewer schräge Wände und runde Deckendurchbrüche richtig.

### Geometrie-Hash

SHA-1 über kanonisches JSON (`sort_keys`, Trenner `,` `:`) von
`{"min": [...], "max": [...], "form": "...", "masse": {...}}`, alle Zahlen als
`round(wert / 5)` (Ganzzahl). Die ersten 16 Hex-Zeichen.

## Status-Berechnung

1. Ein Objekt gehört der Firma, die es zuerst eingereicht hat. `geaendert`/`geloescht`/`eingereicht`
   anderer Firmen werden ignoriert.
2. `geloescht` entfernt das Objekt aus allen Listen (neu `eingereicht` holt es zurück).
3. Je Rolle gilt die letzte `status`-Entscheidung – nur wenn ihr `geometrie_hash` zum aktuellen passt.
4. Beteiligung je Rolle (`pflicht` / `info`) aus `projekt.json` (siehe `projekt.py`).
5. Gesamtstatus:
   - eine Pflichtrolle mit Status der Wirkung `blockiert` → dieser Status (z. B. `abgelehnt`)
   - alle Pflichtrollen mit Wirkung `freigabe` → `freigegeben`
   - sonst `in_pruefung`
6. „Wartet auf mich“:
   - Prüfer: Pflichtrolle ohne gültige Entscheidung, oder nach nicht-freigebender
     Entscheidung wurde erneut eingereicht.
   - Ersteller: eigenes Objekt blockiert und seither nicht erneut eingereicht.

## projekt.json

```json
{
  "id": "3c0d…",
  "name": "Beispielprojekt",
  "rollen": [{"id": "ARC", "name": "Architektur"}, {"id": "TWP", "name": "Tragwerk"}],
  "status": [{"id": "zurueckgestellt", "name": "Zurückgestellt", "wirkung": "offen", "farbe": "#854F0B"}],
  "standard": {"ARC": "pflicht"},
  "regeln": [
    {"name": "Wand tragend", "wenn": {"wirt.kategorie": "Wände", "wirt.tragend": true},
     "rollen": {"ARC": "pflicht", "TWP": "pflicht", "TGA": "info"}},
    {"name": "Groß", "zusatz": true, "wenn": {"flaeche_m2": {"gt": 1.0}},
     "rollen": {"BH": "pflicht"}}
  ]
}
```

- `id`: feste Projekt-ID (beim Anlegen erzeugt, ältere Projekte bekommen sie beim nächsten
  „Übernehmen“). Jedes Revit-Modell merkt sich, zu welcher Projekt-ID es gehört
  (Extensible Storage an den Projektinformationen: `projekt_id`, `projekt_name`,
  `modellkuerzel`) – so fällt ein falscher Projektordner sofort auf. Den Ordnerpfad merkt
  sich jeder Rechner selbst, je Revit-Modell.
- `freigegeben` (Wirkung `freigabe`) und `abgelehnt` (Wirkung `blockiert`) sind immer vorhanden.
- Wirkungen: `freigabe`, `blockiert`, `offen`.
- Normale Regeln: alle passenden vereinigt; passt keine, gilt `standard`.
  Zusatz-Regeln gelten immer zusätzlich. `pflicht` schlägt `info`.
- Bedingungen: Punkt-Pfad in die Objektdaten; Wert = Gleichheit, oder
  `{"gt"|"gte"|"lt"|"lte"|"ne": x}`, `{"in": [...]}`.
