Ziel ist ein Python-Skript (`opals2stac`), das aus einem Verzeichnis mit OPALS-Outputs einen **statischen STAC-Katalog** baut bzw. einen bestehenden erweitert. OPALS dient dabei der **Metadatenextraktion** (ODM, opalsBounds, opalsInfo, opalsGrid). Die Katalogstruktur wird über eine optionale `project.yml`/`project.json` festgelegt; ohne Config soll das Skript mit *sensible defaults* trotzdem einen validen Katalog erzeugen.
# Was soll das Skript können?
Einen statischen STAC Katalog aufbauen.
Einen bestehenden STAC Katalog erweitern.
# Was soll das Skript nicht machen / Was könnte ein eigenes Skript werden?
Tiling
Umwandlung in COPC?
- Solange conversion odm -> copc nicht existiert könnte es im skript stattfinden
- als eigenes skript welches von diesem aufgerufen wird.
ODMs exportieren
# Welche Fragen müssen vorher beantwortet werden?
## Ist es sinnvoll odm files zu katalogisieren?
Große Dateien und nicht Cloud-Native
-> exportieren zu las/laz -> umwandeln in copc
## Was ist eine Collection?
- Jeder (unter-) Ordner in einem vorher festgelegten Verzeichniss (--from-directory):
	- Meist nicht anwendbar, vlt in zukunft implementieren
- Jedes Verzeichniss das explizit in einer yaml / json Datei oder innerhalb Python festgelegt wird (optionales `hierarchy:` Feld, nicht für 1.0)
- Entscheidung sollte getroffen werden wo Collections beginnen und nach welchen extents sie unterteilt werden.
		- Problem: Welche räumliche Abgrenzung? Normalerweise auch Verwaltungsgrenzen üblich?
		- Mögliche Lösung: User die Möglichkeit geben Räumliche Ausdehnung anzugeben bzw als Datei einlesen (shp)
- Können auch ohne diese entscheidung benutzt werden und die extents einfach indifferent zusammenrechnen (am leichtesten für 1.0)
## Was ist ein Item?
- Ein Strip (Ein Item für einen Strip, Tiles sind assets)
- Ein Tile
**Item-Granularität:** *Ein Item pro Stem **pro semantischer Kategorie***. Files mit gleichem Stamm werden gruppiert, aber Pointcloud / Elevation / Orthophoto bleiben getrennte Items in getrennten Collections.
## Wie wird die Hierarchy festgelegt?
- bestehende ordnerstruktur?
	- Problem: Daten sind meistens nicht schön in Ordner aufgeteilt sondern alle in einem, nicht für 1.0
- yaml Datei
**Default-Hierarchie:** *Dynamisch* aus tatsächlich gefundenen Asset-Typen. Leere Zweige werden nicht erzeugt.
### Was ist ein guter default für Kataloge falls nicht über ordnerstruktur festgelegt?
4 Hauptkataloge:
    
Root Catalog (preset: multimodal)
├── Collection: DSM
├── Collection: DTM
├── Collection: Pointclouds
└── Collection: Orthophotos
## Wie muss die `datetime` festgelegt werden?
- `pointcloud`: min/max GPSTime aus ODM via opalsImport (las ≥ 1.2 = adjusted GPS); bei las ≤ 1.1 ohne `gps_week` → fallback file mtime + Warnung.
- `raster` ohne assoziierte Pointcloud: file mtime?
- `raster` mit assoziierter Pointcloud (gleicher Stem): datetime von der Pointcloud erben.
## Welche STAC-Extensions sollen benutzt werden?

| Kategorie         | Extensions                                               |
| ----------------- | -------------------------------------------------------- |
| pointcloud        | `pointcloud`, `projection`, `file`                       |
| elevation_dtm/dsm | `raster`, `projection`, `file`                           |
| orthophoto        | `eo`, `raster`, `projection`, `file`                     |
| (alle)            | `processing` optional, mit `lineage` aus opals cfg-Files |

## Wie soll der CLI call aussehen?
Rangordnung:
CLI Argumente -> YAML -> preset -> defaults
```
opals2stac [-inFile PATH] [-outFile PATH] [-cfgFile PATH]
           [--init] [--preset NAME] [--no-thumb]
           [--unknown-policy {skip,warn,register}]
           [-v]
```
thumbnail size?

| Argument         | Typ     | Beschreibung                                                                                                        |
| ---------------- | ------- | ------------------------------------------------------------------------------------------------------------------- |
| -inFile          | \[str]  | \[optional falls im cfg file angegeben] Pfad zum root Verzeichnis des Katalogs                                      |
| -outFile         | \[str]  | Pfad an dem der Katalog gespeichert werden soll bzw bei -init wo das template gespeichert werden soll. Default: "." |
| -cfgFile         | \[str]  | \[optional] Pfad zur project.yml / json datei                                                                       |
| --init           | \[bool] | Flag: Erstellt eine annotierte Vorlage der project.yml Datei                                                        |
| --no-thumb       | \[bool] | Sollen thumbnails erstellt werden? Default: True                                                                    |
| --preset         | \[str]  | Vordefinierte `project.yml` dateien (Strukturen)                                                                    |
| --unknown-policy | \[str]  | Was mit Dateien gemacht werden soll welche nicht zugeordnert werden können: skip / warn (default) / register        |
### Preset system

| Preset             | Use Case                                                          |
| ------------------ | ----------------------------------------------------------------- |
| `lidar-strips`     | Rohe Befliegungs-Strips, ein Item pro Strip, Pointcloud-zentriert |
| `tiled-pointcloud` | COPC-Tiles, ein Item pro Tile, große Kataloge                     |
| `dem-products`     | DTM/DSM-Lieferung, Elevation-Catalog dominant, optional Hillshade |
| `multimodal`       | Pointcloud + Ortho + DEM gemischt; alle 3 Sub-Kataloge aktiv      |

User kann ein Preset als Startpunkt mit `--init --preset lidar-strips` materialisieren und dann anpassen.
## Wie soll die (optionale) yaml / json project Datei aussehen?
siehe [[project.yml]] 

**Defaults-Modell:** *Auto-Inferenz + optionale Presets*. Default = Daten scannen und Hierarchie ableiten. `--preset <name>` lädt ein vorgefertigtes `project.yml`-Snippet als Override.
### Wenn keine yaml Datei angegeben, welche defaults nehmen?
- !`id` aus dem Verzeichnissnamen ableiten (pielach-tiles -> "pielach-tiles-catalog")
- `title` gleich aber in Titelcase
- !`description` none | default template
- `provider` none
- `temporal_extent` Berechnet aus allen datetimes der items
- `license`  proprietary
Valider STAC Katalog aber nicht veröffentlichbar -> fürs lokale browsen gut
Wenn nicht angegeben -> am ende: Warn

# Asset Registry
Default-Mapping nach OPALS-Konventionen/default werten. Sucht nacht stems mit suffix und file extensions -> assigned ein label -> label definiert in einem role dict welche daten extrahiert werden und wo das item/asset eingeordnet wird. bsp:
```yaml
stem_patterns:
  - { suffix: "",         extension: ".laz",      label: "pointcloud" }
  - { suffix: "",         extension: ".copc.laz", label: "pointcloud_copc" }
  - { suffix: "_dtm",     extension: ".tif",      label: "dtm" }
    
roles:
  dtm:
    category: "elevation_dtm"
    stac_roles: ["data"]
    media_type: "image/tiff; application=geotiff"
    extensions: ["raster", "projection", "file"]
    thumbnail: true
  pointcloud:
    category: "pointcloud"
    stac_roles: ["data"]
    media_type: "application/vnd.laszip"
    extensions: ["pointcloud", "projection", "file"]
    thumbnail: false
```

Projektspezifische Konventionen werden via `asset_overrides` und `role_overrides` in `project.yml` gemerged
# Architektur
```
  CLI / Config-Resolver                                      
  CLI args  >  project.yml/json  >  preset  >  built-in def  
                           ▼
                           
  Layer 1: Asset Discovery + Metadata Extraction             
  - File walker  -> Asset Registry -> (label, role, mediatype)  
  - opalsBounds  -> footprint (WGS84) + bbox                  
  - opalsInfo    -> pcount, pdens, schemas, CRS               
  - opalsImport  -> Datetime aus min/max GPSTime im ODM       
  - GDAL         -> raster: nodata, dtype, res, transform     
  Output: dict pro Datei                          
                           ▼
                           
  Layer 2: STAC Item Builder                                 
  - Gruppiert Files pro (stem, semantic_category)            
  - Erzeugt pystac.Item mit Geometry, Datetime, Properties   
  - Hängt korrekte Extensions an (raster/eo/pointcloud/proj) 
  - Erzeugt optional Thumbnail                               

  Schritt 2b: Hierarchy-Resolver                             
  Funktion: apply_hierarchy(items, hierarchy_cfg)            
    - Bei hierarchy:-Block in cfg -> manuelle Zuordnung       
    - Sonst -> Auto-Hierarchie aus gefundenen Kategorien      
    - Validiert IDs, Match-Regeln, explicit-Item-Refs        
                           ▼
                           
  Layer 3: Catalog Manager                                   
  - Lädt existierenden Katalog falls vorhanden (extend mode) 
  - Erzeugt/aktualisiert Catalog/Collection-Hierarchie       
  - merged Assets bei Match auf ID
  - Schreibt statische JSONs                                 
```


`clfTreeModelTrain.py