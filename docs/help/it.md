<!-- Kalmido help, Italian (2.1072.0, #5820). One block per "How to" section of docs/*.md: the key and the fingerprint (src)
of the English text it was translated from. **Bold** = the label exactly as the interface shows it.
Check: python3 tools/check_userhelp.py. -->

<!-- help: files#how-to-set-up-a-scan-inbox src=64eddd039b -->
## Configurare una casella di scansione

Una casella di scansione invia le nuove scansioni da una cartella del tuo computer direttamente nei tuoi documenti.

1. Apri **Impostazioni** > **Integrazioni** e vai a **Documenti: ingressi**.
2. In **Osservatore cartelle** scarica il programma per il tuo computer (Mac o Windows).
3. Apri **Nuova casella di scansione**, scrivi un **Nome**, scegli la cartella in **Nella cartella** e tocca **Crea casella**.
4. Kalmido mostra il **Codice di configurazione** solo questa volta. Tocca **Copia**, avvia il programma, incolla il codice e
   scegli la cartella da osservare.

Poi: ogni nuovo file di quella cartella viene caricato, letto e archiviato nei tuoi documenti. Ritrovi la casella nello stesso
posto per cambiare cartella, prolungarla di un anno o revocarla. Solo tu crei una casella di scansione, mai un agente.

<!-- help: files#how-to-add-documents-and-find-them-again src=75bd3485cd -->
## Aggiungere documenti e ritrovarli

1. Apri **File** > **Documenti**.
2. Tocca **Aggiungi documenti** e scegli PDF o foto, oppure trascinali sulla pagina. Sul telefono **Scansiona** fotografa
   una lettera.
3. Scrivi una parola in **Cerca nei documenti…**: la ricerca trova anche le parole dentro le lettere.

Poi: Kalmido legge ogni documento e compila data, importo e mittente. Ciò di cui non è sicuro aspetta in **Da verificare**:
aprilo, correggi e tocca **Verificato** (oppure **Accetta tutto** per i suggerimenti).

<!-- help: files#how-to-share-a-folder src=2b0b00ac10 -->
## Condividere una cartella

1. Apri **File** e il menu **Altro** (⋯) della cartella, poi **Condividi…**.
2. In **Condividi con …** scegli una persona, un gruppo o un agente.
3. Scegli **Può vedere** o **Può modificare**, tocca **Aggiungi** e poi **Fatto**.

Poi: la persona vede la cartella e tutto il suo contenuto, anche ciò che verrà aggiunto. Solo il proprietario può condividere
una cartella.

<!-- help: agent-setup#how-to-create-your-personal-agent src=c5dbd2659a -->
## Creare il tuo agente personale

Un agente è un assistente (per esempio Claude) che lavora in Kalmido con un proprio account e vede solo ciò che condividi con lui.

1. Apri **Impostazioni** > **Agenti** e la scheda **Configura**.
2. In **I tuoi agenti personali** compila **Nome visualizzato** e gli altri due campi, poi tocca **Crea agente**.
3. Nella finestra che si apre scegli il tuo **Computer** e la **Cartella del progetto** e tocca **Crea comando**.
4. Tocca **Copia**, apri il Terminale su quel computer, incolla il comando e premi Invio. Poi **Fatto**.

Poi: l'agente compare in **I tuoi agenti personali**. Non vede ancora nulla: dagli un progetto o una cartella. Il comando vale
una volta e per pochi minuti; **Configura** nella riga dell'agente ne crea uno nuovo.

<!-- help: agent-setup#how-to-give-an-agent-access-to-a-project-or-folder src=2e7c802506 -->
## Dare a un agente accesso a un progetto o una cartella

Un progetto:

1. Apri il menu (⋯) del progetto e scegli **Agente…**.
2. In **Agenti** scegli l'agente e conferma con **Condividi**.

Una cartella in File o Conoscenza:

1. Apri il menu (⋯) della cartella e scegli **Condividi…**.
2. In **Condividi con …** scegli l'agente, **Può vedere** o **Può modificare**, tocca **Aggiungi** e poi **Fatto**.

Poi: l'agente lavora in quel progetto o in quella cartella, e solo lì. Ogni accesso di un agente resta nella cronologia; una
cartella bloccata non si condivide mai con un agente.

<!-- help: agent-setup#how-to-approve-what-an-agent-asks-for src=c440cd682e -->
## Approvare ciò che chiede un agente

1. Quando un agente ha bisogno del tuo sì, compare una scheda "… ti aspetta" (in Oggi e in Agenti).
2. Tocca **Approva** o **Rifiuta**. Per una proposta prima **Esamina la proposta**.

Poi: l'agente prosegue con ciò che hai approvato; un passo rifiutato non avviene.

<!-- help: office#how-to-write-a-quotation src=8abb747cdd -->
## Scrivere un preventivo

1. Apri **Ufficio** > **Preventivi** e tocca **Nuovo preventivo**. La bozza si apre subito.
2. Scegli il **Cliente**.
3. Aggiungi righe con **Aggiungi servizio**.
4. Quando è pronto tocca **Bloccare**. Dopo, numero, righe e importi non cambiano più.
5. Tocca **Invia** per mandarlo via e-mail, oppure **Scarica PDF**.

Poi: il preventivo è nella lista. Segnalo come inviato e poi come **Accettato** o rifiutato; da un preventivo accettato nasce
la fattura in un passo. Una bozza si guarda con **Anteprima**.

<!-- help: office#how-to-turn-a-quotation-into-an-invoice src=b1c09e308f -->
## Trasformare un preventivo in fattura

1. Apri il preventivo accettato e tocca **Crea fattura**.
2. Scegli il **Tipo di fattura** e conferma.
3. Controlla la fattura, tocca **Bloccare** e poi **Invia**.

Una fattura senza preventivo: **Ufficio** > **Fatture** > **Nuova fattura**.

Poi: la fattura riceve il suo numero quando la blocchi, senza buchi. Resta aperta finché non si registra un pagamento.

<!-- help: office#how-to-record-a-payment src=c83bb01e09 -->
## Registrare un pagamento

1. Apri la fattura bloccata e tocca **Registra pagamento**.
2. Controlla data e importo e tocca **Registra**.

Oppure con l'estratto conto: **Ufficio** > **Banca** > **Importa estratto conto** e conferma il suggerimento con **Subentra**.

Poi: la fattura risulta pagata (o pagata in parte). Solo un amministratore dell'organizzazione registra i pagamenti.

<!-- help: tasks#how-to-add-a-task-with-a-date src=c89121e185 -->
## Aggiungere un'attività con una data

1. Tocca **Aggiungi attività…** in fondo al progetto (sul telefono: il pulsante +).
2. Scrivi l'attività come la pensi, per esempio "Chiamare il dentista domani 15", oppure scegli la data.
3. Premi Invio.

Poi: l'attività finisce nel progetto aperto (o nella **Raccolta**) con la sua data e compare quel giorno in **Oggi**. Per
cambiare la data apri l'attività e tocca la data: **Oggi**, **Domani**, **Prossima settimana** o un giorno del calendario.

<!-- help: tasks#how-to-make-a-task-repeat src=7fb71b25d1 -->
## Ripetere un'attività

Un'attività ricorrente torna da sola: ogni giorno, ogni settimana o con una regola tua.

1. Apri l'attività e tocca la sua data.
2. Scegli in **Ripetizione**, per esempio **Ogni giorno**, oppure **Personalizza…** per una regola tua.
3. Tocca **Fatto**.

Poi: quando completi l'attività compare la successiva con la prossima data.

<!-- help: tasks#how-to-assign-a-task-or-share-a-project src=26bbda819e -->
## Assegnare un'attività o condividere un progetto

1. Condividere il progetto: il suo menu (⋯) > **Condividi…**, scegli la persona in **Condividi con …**, un ruolo (per esempio
   **Membro**) e tocca **Aggiungi**.
2. Assegnare un'attività: apri l'attività, tocca **Assegna** e scegli la persona.

Poi: la persona vede il progetto e riceve l'attività. Si può assegnare solo a persone del progetto.

<!-- help: calendar#how-to-create-an-event src=a00f1c721d -->
## Creare un evento

1. Apri **Calendario** e tocca **Evento** (sul telefono: il pulsante +).
2. Compila **Titolo**, **Inizio** e **Termina** e, se serve, **Ripetizione**.
3. Tocca **Salva**.

Poi: l'evento è nel calendario e sul tuo telefono, se è collegato.

<!-- help: calendar#how-to-subscribe-to-another-calendar src=a8d8302f42 -->
## Abbonarsi a un altro calendario

1. Apri **Calendario** > **Calendari** > **Abbonamenti…** (oppure **Impostazioni** > **Integrazioni** > **Calendari**).
2. Tocca **Aggiungi calendario**.
3. Incolla il link del calendario e tocca **Aggiungi**. Per un account scegli **Account CalDAV** e **Trova calendari**.

Poi: i suoi eventi compaiono nel tuo calendario, in sola lettura e solo per te.

<!-- help: calendar#how-to-show-kalmido-on-your-phone src=e055eae2f6 -->
## Vedere Kalmido sul telefono

1. Apri **Calendario** > **Calendari** > **Sul telefono…** (oppure **Impostazioni** > **Integrazioni** > **App calendario (CalDAV)**).
2. Tocca **Nuova password per app** e copia server, nome utente e password nelle impostazioni del calendario del telefono.

Poi: i tuoi eventi e le attività con data compaiono nel calendario del telefono. Usa lì la password per app, mai la tua
password di Kalmido.
