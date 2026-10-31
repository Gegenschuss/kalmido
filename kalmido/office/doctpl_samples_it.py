"""2.449.0 (#3768): the samples in Italian, translated when they were built (Kalmido never calls a language model). Same keys,
variables and [[optional parts]] as the English samples; the legal samples say on their second line that the translation
must be checked. SAMPLES = doctpl.DT_STARTERS + doctpl_samples.DMA_SAMPLES, BLOCKS = lettermail.LTB_STARTERS."""

SAMPLES = {
    "contract": ("Contratto di prestazione di servizi", """# Contratto di prestazione di servizi

Tra {{company.name}}[[, {{company.address}}]] (il fornitore)
e {{client.name}}[[, {{client.address}}]] (il cliente)

## 1. Oggetto
Il fornitore presta servizi al cliente[[ nel progetto {{project.title}}]][[ secondo il preventivo {{offer.number}}]][[ del {{offer.date}}]].

## 2. Compenso
Il compenso è stabilito dal preventivo[[ e ammonta a {{offer.net}} più IVA]]. Le fatture sono pagabili entro {{payment.days}} giorni senza detrazioni.

## 3. Collaborazione
Il cliente fornisce per tempo i documenti e le informazioni necessari.[[ Referente presso il cliente: {{client.contact}}.]]

## 4. Diritti di utilizzo
I diritti di utilizzo si trasferiscono nella misura concordata al pagamento integrale.

## 5. Disposizioni finali
Modifiche e integrazioni devono essere fatte per iscritto. Se una clausola è invalida, il resto del contratto rimane valido.

Data: {{today}}"""),
    "confirmation": ("Conferma d'ordine", """# Conferma d'ordine

Gentili Signore e Signori,

vi ringraziamo per il vostro ordine. Confermiamo l'ordine[[ secondo il nostro preventivo {{offer.number}}]][[ del {{offer.date}}]][[ per il progetto {{project.title}}]].

- Cliente: {{client.name}}
- Referente: {{client.contact}}
- Importo dell'ordine: {{offer.net}} più IVA

Valgono le condizioni del preventivo. Vi preghiamo di controllare i dati e di segnalarci eventuali inesattezze.

Cordiali saluti
{{company.name}}"""),
    "nda": ("Accordo di riservatezza", """# Accordo di riservatezza

[Traduzione automatica, verificare prima dell'uso: poi cancellare questa riga.]

Tra {{company.name}}[[, {{company.address}}]]
e {{client.name}}[[, {{client.address}}]]

## 1. Informazioni riservate
Sono riservate tutte le informazioni che una parte comunica all'altra nell'ambito della collaborazione[[ nel progetto {{project.title}}]] e che sono indicate come riservate o riconoscibili come tali.

## 2. Obblighi
Le parti utilizzano le informazioni riservate solo per il progetto, non le trasmettono a terzi e le proteggono con la dovuta diligenza.

## 3. Eccezioni
Gli obblighi non si applicano alle informazioni pubbliche, a quelle che una parte conosceva già legittimamente o che deve divulgare per legge.

## 4. Durata
Il presente accordo vale dal {{today}} e termina tre anni dopo la fine della collaborazione."""),
    "letter": ("Lettera di accompagnamento", """# [Oggetto]

Gentili Signore e Signori,

[Il vostro testo]

Per qualsiasi domanda non esitate a contattarci.

Cordiali saluti
{{company.name}}"""),
    "reminder": ("Sollecito di pagamento", """# Sollecito di pagamento

Gentili Signore e Signori,

forse vi è sfuggito: non abbiamo ancora ricevuto il pagamento della fattura [numero fattura] del [data fattura] per un importo di [importo].

Vi preghiamo di versare l'importo dovuto entro il [data] sul conto indicato in fattura. Se avete già pagato, vi preghiamo di ignorare questa lettera.

Cordiali saluti
{{company.name}}"""),
    "dunning": ("Diffida di pagamento", """# Diffida di pagamento

Gentili Signore e Signori,

nonostante il nostro sollecito di pagamento del [data del sollecito], la fattura [numero fattura] del [data fattura] per un importo di [importo] risulta ancora aperta.

Vi preghiamo di saldare l'importo dovuto entro e non oltre il [termine]. Decorso tale termine ci riserviamo di intraprendere ulteriori azioni.

Se avete già pagato, vi preghiamo di ignorare questa lettera.

Cordiali saluti
{{company.name}}"""),
    "termination": ("Disdetta", """# Disdetta del contratto [contratto / numero di contratto]

Gentili Signore e Signori,

con la presente disdiciamo il contratto sopra indicato nei termini previsti con effetto dal [data] o, in subordine, alla prima data possibile.

Vi preghiamo di confermarci per iscritto il ricevimento della presente disdetta e la data di fine del contratto.

Cordiali saluti
{{company.name}}

{{today}}"""),
    "authority": ("Procura", """# Procura

{{client.name}}
{{client.address}}

autorizza con la presente

{{company.name}}
{{company.address}}

a compiere i seguenti atti in nome del mandante nel progetto {{project.title}}:

- [atto 1]
- [atto 2]

La presente procura vale dal {{today}} al [data] e può essere revocata in qualsiasi momento. La subdelega [non] è consentita."""),
    "handover": ("Verbale di consegna", """# Verbale di consegna

Progetto: {{project.title}}
Consegna da {{company.name}} a {{client.name}}
Referente: {{client.contact}}
Data: {{today}}

## Consegnato
- [oggetto / fornitura 1]
- [oggetto / fornitura 2]

## Stato e osservazioni
[stato, parti mancanti, punti aperti]

## Conferma
Il cliente conferma di aver ricevuto le prestazioni sopra indicate nello stato descritto."""),
    "credit": ("Lettera di accompagnamento della nota di credito", """# La vostra nota di credito [numero nota di credito]

Gentili Signore e Signori,

in allegato trovate la nostra nota di credito [numero nota di credito] del {{today}} per un importo di [importo] relativa alla fattura [numero fattura] del progetto {{project.title}}.

[Trasferiremo l'importo sul vostro conto entro la data / Compenseremo l'importo con la prossima fattura].

Cordiali saluti
{{company.name}}"""),
    "privacy_dpa": ("Accordo sul trattamento dei dati", """# Accordo sul trattamento dei dati

[Testo di esempio, non è consulenza legale. Traduzione automatica, verificare prima dell'uso: adattarlo all'incarico e cancellare questa riga.]

Tra {{client.name}}, {{client.address}} (titolare del trattamento)
e {{company.name}}, {{company.address}} (responsabile del trattamento)

## 1. Oggetto e durata
Il responsabile tratta dati personali per conto del titolare per i seguenti servizi: [servizi]. La durata segue quella dell'incarico sottostante.

## 2. Natura e finalità del trattamento
[natura e finalità, ad es. archiviazione, manutenzione, analisi]

## 3. Tipi di dati e interessati
- Tipi di dati personali: [ad es. dati di contatto, dati contrattuali]
- Categorie di interessati: [ad es. clienti, dipendenti]

## 4. Istruzioni
Il responsabile tratta i dati soltanto su istruzione documentata del titolare (art. 28, par. 3, lett. a), GDPR).

## 5. Riservatezza
Le persone autorizzate al trattamento sono tenute alla riservatezza (art. 28, par. 3, lett. b), GDPR).

## 6. Sicurezza del trattamento
Il responsabile adotta le misure tecniche e organizzative dell'art. 32 GDPR: [misure o allegato].

## 7. Altri responsabili
Altri responsabili sono coinvolti solo previa autorizzazione del titolare (art. 28, par. 2 e 4, GDPR). Attualmente: [nessuno / elenco].

## 8. Assistenza
Il responsabile assiste il titolare nelle richieste degli interessati e negli obblighi degli art. da 32 a 36 GDPR (art. 28, par. 3, lett. e) e f), GDPR).

## 9. Cancellazione e restituzione
Al termine dei servizi i dati vengono cancellati o restituiti a scelta del titolare, salvo obbligo di conservazione per legge (art. 28, par. 3, lett. g), GDPR).

## 10. Prove e verifiche
Il responsabile mette a disposizione le informazioni necessarie a dimostrare il rispetto degli obblighi e consente le verifiche (art. 28, par. 3, lett. h), GDPR).

## 11. Notifica delle violazioni
Il responsabile notifica una violazione dei dati personali senza ingiustificato ritardo dopo esserne venuto a conoscenza (art. 33, par. 2, GDPR).

Data: {{today}}"""),
    "privacy_info": ("Informativa sulla privacy", """# Informativa sulla privacy

[Testo di esempio, non è consulenza legale. Traduzione automatica, verificare prima dell'uso: completarlo e cancellare questa riga.]

Informazioni ai sensi degli art. 13 e 14 GDPR per {{client.name}}

## 1. Titolare del trattamento
{{company.name}}, {{company.address}}

## 2. Finalità e basi giuridiche
Trattiamo i vostri dati per preparare ed eseguire un contratto con voi (art. 6, par. 1, lett. b), GDPR), per adempiere obblighi di legge come i doveri di conservazione (art. 6, par. 1, lett. c), GDPR) e qualora abbiate dato il consenso (art. 6, par. 1, lett. a), GDPR).

## 3. Categorie di dati
[ad es. nome, indirizzo, dati di contatto, dati contrattuali e di fatturazione]

## 4. Destinatari
[ad es. consulente fiscale, fornitore di hosting come responsabile del trattamento]

## 5. Trasferimenti verso paesi terzi
[nessuno / dettagli]

## 6. Periodo di conservazione
Conserviamo i vostri dati per il tempo necessario a queste finalità e oltre, se valgono termini legali di conservazione: [termini].

## 7. I vostri diritti
- Accesso, rettifica, cancellazione e limitazione del trattamento (art. da 15 a 18 GDPR)
- Portabilità dei dati (art. 20 GDPR) e opposizione (art. 21 GDPR)
- Revoca del consenso in qualsiasi momento con effetto per il futuro (art. 7, par. 3, GDPR)
- Reclamo a un'autorità di controllo per la protezione dei dati (art. 77 GDPR)

## 8. Conferimento dei dati
Abbiamo bisogno dei dati richiesti per il contratto per concluderlo ed eseguirlo. [responsabile della protezione dei dati, se nominato]

Aggiornamento: {{today}}"""),
    "privacy_consent": ("Consenso al trattamento dei dati", """# Consenso al trattamento dei dati

[Testo di esempio, non è consulenza legale. Traduzione automatica, verificare prima dell'uso: adattarlo e cancellare questa riga.]

{{client.name}}, rappresentato da {{client.contact}}, acconsente al trattamento da parte di {{company.name}} dei seguenti dati personali:

- Dati: [dati]
- Finalità: [finalità]

## Volontarietà e revoca
Il consenso è volontario. Può essere revocato in qualsiasi momento senza indicarne i motivi con effetto per il futuro (art. 7, par. 3, GDPR), ad esempio via e-mail a [indirizzo e-mail]. La revoca non pregiudica la liceità del trattamento precedente.

Ulteriori informazioni sono riportate nella nostra informativa sulla privacy.

Data: {{today}}"""),
}

BLOCKS = {
    "cancel": ("Disdetta", "con la presente disdico il contratto sopra indicato nei termini previsti alla prima data possibile. "
                           "Vi prego di confermarmi per iscritto la disdetta e la data da cui ha effetto."),
    "objection": ("Ricorso", "con la presente presento ricorso contro il vostro provvedimento del [data], riferimento [riferimento]. Invierò le "
                             "motivazioni separatamente. Vi prego di confermarmi il ricevimento di questa lettera."),
    "reminder": ("Sollecito di pagamento", "forse vi è sfuggito: l'importo di [importo] della nostra fattura [numero] del [data] risulta ancora aperto. "
                                           "Vi preghiamo di versarlo entro il [data]. Se avete già pagato, vi preghiamo di ignorare questa lettera."),
    "extension": ("Richiesta di proroga", "vi chiedo cortesemente di prorogare il termine del [data] fino al [data], poiché mi mancano ancora alcuni "
                                          "documenti. Vi ringrazio per la comprensione."),
}
