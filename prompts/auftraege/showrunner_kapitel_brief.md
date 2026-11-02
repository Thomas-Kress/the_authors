## Auftrag: Kapitel-Brief
Erstelle den Kapitel-Brief für Kapitel {{kapitel_nr}} (typ = "kapitel_brief").
Grundlage ist die Zeile des Kapitelplans in <kapitelplan> und der bisherige
Verlauf in <zusammenfassungen>.

Pflichtfelder in "inhalt" zusätzlich zum Übergabeformat:
- "kapitel_typ": einer von {{kapitel_typen}} (Standard: "prosa").
- "{{brief_feld}}": das projektspezifische Feld aus Bible 4.3.

Braucht die Geschichte eine Abweichung von der Bible, antworte stattdessen mit
typ = "bible_aenderung" und inhalt = {"abschnitt": "<Nr.>", "vorschlag": "...",
"begruendung": "..."}.
