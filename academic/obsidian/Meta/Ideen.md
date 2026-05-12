# Implementierung
Python Skript, dass die Daten katalogisiert.
~~Das Skript soll weitere kleine Skripts aufrufen welche die einzelnen Sachen verbindet bsp:
- ~~Skript für Geländemodelle
- ~~Skript für Punktwolken~~
Es sollte so funktionieren dass der bestehende Katalog erweitert / items gelöscht werden und nicht jedes Mal der Katalog neu generiert wird wenn etwas dazukommt / wegfällt. Ein Skript sollte reichen
# JSON-**Structures**
Hier wird etwas stehen. ~~Additional Fields fürs Item könnte die anderen Arten von katalogisierbaren Assets. Z.b. Punktwolke eines Ortes könnte relationship link zu Modellen haben~~ Es wird Grundsätzlich von extra Feldern abgeraten sofern sie nicht bei der Suche helfen

# Offene Fragen
- Brauche Ich Tiles?
	- Copc files kümmern sich eigentlich um die spatial queries
	- Mit tiles könnte ich eine interessantere Bachelorarbeit schreiben
	- Preferably Tiles (als copc files) -> Ältere Software kann nur die betroffenen Tiles downloaded, streamer können nur die bytes aus den tiles rauslesen die sie brauchen. Also warum nicht beides.
	- Die Modelle sind keine großen Dateien d.h sie zu kacheln wäre dumm
		- Alternativen:
			- Möglichkeit Collections nach Produkt zu kategorisieren anstatt nach Zeitpunkt
			- Möglichkeit custom STAC properties hinzuzufügen, damit man es filtern kann
			- ![[STAC Struktur#How to handle tiles]]
