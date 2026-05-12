## Innerhalb Opals:
- Für item geometry und bbox:
	- opalsBounds (boundsType convexHull)
	- las_header
- Für datetime:
	- start_datetime / end_datetime:
		- von min/max gpstime im odm
	- ansonsten eine fixe Zeit auch möglich
- Für pointcloud STAC extension:
	- oaplsInfo:
		- pdens
		- pcount
		- verfügbare attribude (`pointcloud:schemas`)
		- crs
- Für processing extension:
	- `processing:lineage` config files der ausgeführten Module können für die Reproduzierbarkeit angehängt werden. 
- Für Raster:
	- opalsGrid / opalsSurface: metadaten (welche?)

## Asset Discovery:
### Auto-discovery mit wildcards
Aufbau eines Role dictionary: Verknüpfung von Standardwerten der opalsModule mit den Rollen und Media-types von STAC
- `*.odm` -> `data`, role `point-cloud`
- `_dtm.tif` -> `data`, role `dtm`
- `*_bounds.*` -> `metadata`, role `footprint`
Sollte konfigurierbar sein falls jemand anderen Konventionen benutzt

## Catalog scope vs. item scope
Ein Katalog beschreibt alle darin enthaltenen Items. Das Skript muss also wissen ob es eine neue Collection baut oder eine alte erweitert. Lösung: cfg-file oder programmatisch festlegen an welchen stellen ein (sub-) Katalog aufgebaut werden soll.

## Das Register:
Es muss für jede Datei beantworten können:
- Ist es ein bekanntes STAC Asset?
- Welche `role` hat es?
- Welche Metadaten müssen extrahiert werden?
Wie machen?
- stem patterns (aus las?)
	- (suffix, extension) Paare finden; bsp: ("\_dtm","tif")
	- ```yaml
	  stem_patterns:
		- suffix: "_z"
		    extension: ".tif"
		    label: "dsm"
		- ...
	  ```
- -> Use that to map to Stac asset types:
	```yaml
	dsm:
		stac_roles: ["data", "visual"]
		media_type: "image/tiff; application=geotiff"
		title: "Digital Surface Model"
		extensions: ["raster", "projection"]
		thumbnail: true
	```
- Fallback für nicht erkannte Datein: warn
- Overrides sollen möglich sein
```yaml
asset_overrides:
	- suffix: "_ground"
	  extension: ".tif"
	  label: "dtm_candidate"
```

## Manuelle Hierarchie
- Optionaler `hierarchy:`-Block in `project.yml` (siehe `project.yml.md`).
- Anwesenheit → manueller Modus, Asset-Discovery + Metadaten-Extraktion laufen weiter; nur Catalog/Collection-Tree wird vom User vorgegeben.
- Eigene Funktion `apply_manual_hierarchy(items, hierarchy_cfg)` zwischen Builder und Catalog-Manager.
- Match-Regeln: `categories`, `path_glob`, `stem_regex`, `not_match`. Erstes Match gewinnt.
- Validierung **vor** Discovery: id-Eindeutigkeit, xor `items:`/`match:`, explicit-href-Existenz, Pattern-Compile.
- `--init --hierarchy {explicit, match}` generiert Skelett aus Daten.
