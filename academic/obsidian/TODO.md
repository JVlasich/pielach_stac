# Phase 1 - recherche
---
- [x] [[STAC Struktur]] 1.1 komplett lesen
- [x] [[Extensions]] durcharbeiten
- [ ] [[PyStack]]-Doku lesen, mini besipielkatalog machen
- [x] Rieg et al. (2014) lesen, notizen machen
- [ ] FAIR-Prinzipien-Paper durchgehen, Mapping zu STAC-Features notieren, auch für eigene Arbeit anwenden
- [x] Notieren welche Metadatenfelder pro [[Asset-types]] tatsächlich gebraucht werden (Footprint, Zeit, CRS, Punktdichte, Bänder usw.)
- [ ] Vergleichbare STAC-Kataloge durchgehen und Struktur notieren ([[Related-Catalogs]])
- [x] LaTex aufsetzen, Reference Manager einrichten
# Phase 2 - mapping
---
- [ ] Kompletten Verzeichnissbaum durchgehen, Struktur dokumentieren
- [ ] Datentypen und Formate notieren [[Asset-types]]
- [ ] Namenskonvention erfassen (üblich, opals-default, inkonsistent)
- [ ] Stichprobenhaltig crs, extent, auflösung für einzelne Dateien notieren
- [ ] Was macht 2023 zum besten jahr?
# Phase 3 - pre-processing
---
siehe auch [[pre-processing]]
- [ ] Skript: Raster → COG (mit GDAL, validieren mit `rio cogeo validate` o. ä.)
- [ ] Punktwolken-Strategie festlegen: kacheln ja/nein, Tile-Größe, Overlap
- [ ] Skript: LAZ → COPC (PDAL)
- [ ] idempotenz gewährleisten
# Phase 4 - Architektur
---
- [ ] Mehrere Varianten skizzieren und gegeneinander abwägen
- [ ] Tile-Handling: ein Item pro Tile, oder Item pro Datensatz mit mehreren Assets?
- [ ] Linking-Strategie: relativ vs. absolut. Implikationen für Portabilität durchdenken
- [ ] Asset-Registry: Datenmodell für Mapping `Dateimuster → Asset-Rolle` festlegen (JSON/YAML/.cfg)
- [ ] Erweiterbarkeit: wie neuen Datensatz hinzufügen ohne Probleme
- [ ] Idempotenz-Konzept: wie wird erkannt was schon im Katalog ist (Hashes? Pfade? IDs?)
- [ ] Strategie für nicht erkannte assets klären
# Phase 5 - Implementierung
---
- [ ] Proof of Concept auf einem Jahresdatensatz
	- [ ] Crawler für Verzeichnisbaum
	- [ ] Metadatenextraktion pro Asset-Typ
	- [ ] STAC-Item-Erzeugung mit PySTAC
	- [ ] Collection- und Catalog-Aufbau
	- [ ] Schreiben des statischen Katalogs auf Disk
- [ ] Asset-Registry aus Code rauslösen, konfigurierbar machen
- [ ] Idempotenz einbauen und mit doppeltem Lauf testen
- [ ] Update-Pfad: neuer Datensatz wird ergänzt, alter nicht zerstört
- [ ] Logging
- [ ] Pipeline auf gesamte Zeitreihe laufen lassen
- [ ] Validierung
	- [ ] Automatisiert: `pystac validate`, `stac-validator` über kompletten Katalog
	- [ ] Bounding Boxes gegen Originaldaten checken
	- [ ] CRS-Angaben stichprobenartig prüfen
	- [ ] Zeitstempel prüfen (UTC, Format, Plausibilität)
	- [ ] Katalog in stac-browser laden
	- [ ] Edge Cases