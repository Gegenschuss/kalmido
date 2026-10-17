# Privacy wording for the built-in assistant (draft)

**Draft – the operator fills in provider and contract details.** Not legal advice. Kalmido's [built-in
assistant](ASSISTANT.md) (2.75.0) sends texts to the provider the operator configured. If you run Kalmido for other
people, the provider is a sub-processor; the two blocks below are starting points for your sub-processor list and your
privacy policy. Replace every `<…>` and check the wording against your contract.

## 1. Line for the list of sub-processors

**Deutsch**

| Unterauftragnehmer | Ort der Verarbeitung | Zweck | Rechtsgrundlage |
|--------------------|----------------------|-------|-----------------|
| `<Anbieter>` | `<Ort>` | Verarbeitung von Aufgabentexten für den eingebauten Assistenten (nur wenn die Person ihn eingeschaltet hat und auf ihren Anstoß) | Auftragsverarbeitungsvertrag nach Art. 28 DSGVO; laut Vertrag keine Speicherung über die Anfrage hinaus und keine Verwendung zum Training |

**English**

| Sub-processor | Place of processing | Purpose | Legal basis |
|---------------|---------------------|---------|-------------|
| `<Provider>` | `<Location>` | Processing of task texts for the built-in assistant (only when the person switched it on, and only on their request) | Data processing agreement under Art. 28 GDPR; per contract no storage beyond the request and no use for training |

## 2. Paragraph for the privacy policy

**Deutsch**

> **Eingebauter Assistent.** Kalmido enthält einen optionalen Assistenten, der Aufgaben zusammenfasst, Antworten
> entwirft und Vorschläge macht (Aufgaben, Tags, Fälligkeit, Sortierung des Korbs, Tagesplan). Er ist
> standardmäßig ausgeschaltet. Erst wenn du ihn in den Einstellungen einschaltest und Listen für ihn freigibst, und
> nur wenn du ihn ausdrücklich fragst, senden wir die Texte der gewählten Aufgaben (Titel, Notiz, Kommentare bzw. Tags
> und Termine) an `<Anbieter>` in `<Ort>`. Gesperrte Notizen, Gesundheitslisten, Anhänge und Dateien werden nie
> gesendet; Aufgaben aus dem Korb nur, wenn du sie selbst auswählst. Ergebnisse sind Vorschläge, die du annimmst oder
> ablehnst. Wir protokollieren jeden Aufruf mit Zeit, Art, Status und Länge, nicht aber die Texte selbst; das
> Protokoll siehst du in den Einstellungen und es wird nach `<Tage>` Tagen gelöscht. Rechtsgrundlage ist Art. 6 Abs. 1
> lit. b DSGVO (Bereitstellung der von dir gewählten Funktion). Du kannst den Assistenten jederzeit wieder
> ausschalten; danach werden keine Texte mehr gesendet.

**English**

> **Built-in assistant.** Kalmido includes an optional assistant that summarizes tasks, drafts replies and makes
> proposals (tasks, tags, due dates, sorting the basket, a day plan). It is off by default. Only once you switch it on
> in the settings and share lists with it, and only when you explicitly ask it, do we send the texts of the chosen
> tasks (title, note, comments, or tags and dates) to `<Provider>` in `<Location>`. Locked notes, health lists,
> attachments and files are never sent; basket tasks only when you pick them yourself. Results are proposals you accept
> or reject. We log every call with its time, kind, status and length, but not the texts themselves; you see the log in
> the settings, and it is deleted after `<days>` days. The legal basis is Art. 6(1)(b) GDPR (providing the feature you
> chose). You can switch the assistant off at any time; from then on no texts are sent.
