<!-- Kalmido help, Italian (2.1086.0, #5820). One block per "How to" section of docs/*.md: the key and the fingerprint (src)
of the English text it was translated from. **Bold** = the label exactly as the interface shows it.
Check: python3 tools/check_userhelp.py. -->

<!-- help: files#how-to-set-up-a-scan-inbox src=b33c638618 -->
## Configurare una casella di scansione

Una casella di scansione invia le nuove scansioni da una cartella del tuo computer direttamente nei tuoi documenti.

1. Apri **Impostazioni** > **Integrazioni** e vai a **Documenti: ingressi**.
2. In **Osservatore cartelle** scarica il programma per il tuo computer (Mac o Windows).
3. Apri **Nuova casella di scansione**, scrivi un **Nome**, scegli la cartella in **Nella cartella** e tocca **Crea casella**.
4. Kalmido mostra il **Codice di configurazione** solo questa volta. Tocca **Copia**, avvia il programma, incolla il codice e
   scegli la cartella da osservare.

Poi: ogni nuovo file di quella cartella viene caricato, letto e archiviato nei tuoi documenti. Ritrovi la casella nello stesso
posto per cambiare cartella, prolungarla di un anno o revocarla. Solo tu crei una casella di scansione, mai un agente.

<!-- help: files#how-to-add-documents-and-find-them-again src=4520b96808 -->
## Aggiungere documenti e ritrovarli

1. Apri **File** > **Documenti**.
2. Tocca **Aggiungi documenti** e scegli PDF o foto, oppure trascinali sulla pagina. Sul telefono **Scansiona** fotografa
   una lettera.
3. Scrivi una parola in **Cerca nei documenti…**: la ricerca trova anche le parole dentro le lettere.

Poi: Kalmido legge ogni documento e compila data, importo e mittente. Ciò di cui non è sicuro aspetta in **Da verificare**:
aprilo, correggi e tocca **Verificato** (oppure **Accetta tutto** per i suggerimenti).

<!-- help: files#how-to-share-a-folder src=f6f99fa88e -->
## Condividere una cartella

1. Apri **File** e il menu **Altro** (⋯) della cartella, poi **Condividi…**.
2. In **Condividi con …** scegli una persona, un gruppo o un agente.
3. Scegli **Può vedere** o **Può modificare**, tocca **Aggiungi** e poi **Fatto**.

Poi: la persona vede la cartella e tutto il suo contenuto, anche ciò che verrà aggiunto. Solo il proprietario può condividere
una cartella.

<!-- help: agent-setup#how-to-create-your-personal-agent src=55f8406267 -->
## Creare il tuo agente personale

Un agente è un assistente (per esempio Claude) che lavora in Kalmido con un proprio account e vede solo ciò che condividi con lui.

1. Apri **Impostazioni** > **Agenti** e la scheda **Configura**.
2. In **I tuoi agenti personali** compila **Nome visualizzato** e gli altri due campi, poi tocca **Crea agente**.
3. Nella finestra che si apre scegli il tuo **Computer** e la **Cartella del progetto** e tocca **Crea comando**.
4. Tocca **Copia**, apri il Terminale su quel computer, incolla il comando e premi Invio. Poi **Fatto**.

Poi: l'agente compare in **I tuoi agenti personali**. Non vede ancora nulla: dagli un progetto o una cartella. Il comando vale
una volta e per pochi minuti; **Configura** nella riga dell'agente ne crea uno nuovo.

<!-- help: agent-setup#how-to-give-an-agent-access-to-a-project-or-folder src=aaf357fa82 -->
## Dare a un agente accesso a un progetto o una cartella

Un progetto:

1. Apri il menu (⋯) del progetto e scegli **Agente…**.
2. In **Agenti** scegli l'agente e conferma con **Condividi**.

Una cartella in File o Conoscenza:

1. Apri il menu (⋯) della cartella e scegli **Condividi…**.
2. In **Condividi con …** scegli l'agente, **Può vedere** o **Può modificare**, tocca **Aggiungi** e poi **Fatto**.

Poi: l'agente lavora in quel progetto o in quella cartella, e solo lì. Ogni accesso di un agente resta nella cronologia; una
cartella bloccata non si condivide mai con un agente.

<!-- help: agent-setup#how-to-approve-what-an-agent-asks-for src=dfbe19a2e9 -->
## Approvare ciò che chiede un agente

1. Quando un agente ha bisogno del tuo sì, compare una scheda "… ti aspetta" (in Oggi e in Agenti).
2. Tocca **Approva** o **Rifiuta**. Per una proposta prima **Esamina la proposta**.

Poi: l'agente prosegue con ciò che hai approvato; un passo rifiutato non avviene.

<!-- help: office#how-to-write-a-quotation src=c3eae76ef0 -->
## Scrivere un preventivo

1. Apri **Ufficio** > **Preventivi** e tocca **Nuovo preventivo**. La bozza si apre subito.
2. Scegli il **Cliente**.
3. Aggiungi righe con **Aggiungi servizio**.
4. Quando è pronto tocca **Bloccare**. Dopo, numero, righe e importi non cambiano più.
5. Tocca **Invia** per mandarlo via e-mail, oppure **Scarica PDF**.

Poi: il preventivo è nella lista. Segnalo come inviato e poi come **Accettato** o rifiutato; da un preventivo accettato nasce
la fattura in un passo. Una bozza si guarda con **Anteprima**.

<!-- help: office#how-to-turn-a-quotation-into-an-invoice src=faeae491ab -->
## Trasformare un preventivo in fattura

1. Apri il preventivo accettato e tocca **Crea fattura**.
2. Scegli il **Tipo di fattura** e conferma.
3. Controlla la fattura, tocca **Bloccare** e poi **Invia**.

Una fattura senza preventivo: **Ufficio** > **Fatture** > **Nuova fattura**.

Poi: la fattura riceve il suo numero quando la blocchi, senza buchi. Resta aperta finché non si registra un pagamento.

<!-- help: office#how-to-record-a-payment src=6663fe7a8c -->
## Registrare un pagamento

1. Apri la fattura bloccata e tocca **Registra pagamento**.
2. Controlla data e importo e tocca **Registra**.

Oppure con l'estratto conto: **Ufficio** > **Banca** > **Importa estratto conto** e conferma il suggerimento con **Subentra**.

Poi: la fattura risulta pagata (o pagata in parte). Solo un amministratore dell'organizzazione registra i pagamenti.

<!-- help: tasks#how-to-add-a-task-with-a-date src=8a3685b666 -->
## Aggiungere un'attività con una data

1. Tocca **Aggiungi attività…** in fondo al progetto (sul telefono: il pulsante +).
2. Scrivi l'attività come la pensi, per esempio "Chiamare il dentista domani 15", oppure scegli la data.
3. Premi Invio.

Poi: l'attività finisce nel progetto aperto (o nella **Raccolta**) con la sua data e compare quel giorno in **Oggi**. Per
cambiare la data apri l'attività e tocca la data: **Oggi**, **Domani**, **Prossima settimana** o un giorno del calendario.

<!-- help: tasks#how-to-make-a-task-repeat src=b22f5f0a3c -->
## Ripetere un'attività

Un'attività ricorrente torna da sola: ogni giorno, ogni settimana o con una regola tua.

1. Apri l'attività e tocca la sua data.
2. Scegli in **Ripetizione**, per esempio **Ogni giorno**, oppure **Personalizza…** per una regola tua.
3. Tocca **Fatto**.

Poi: quando completi l'attività compare la successiva con la prossima data.

<!-- help: tasks#how-to-assign-a-task-or-share-a-project src=d8a87df384 -->
## Assegnare un'attività o condividere un progetto

1. Condividere il progetto: il suo menu (⋯) > **Condividi…**, scegli la persona in **Condividi con …**, un ruolo (per esempio
   **Membro**) e tocca **Aggiungi**.
2. Assegnare un'attività: apri l'attività, tocca **Assegna** e scegli la persona.

Poi: la persona vede il progetto e riceve l'attività. Si può assegnare solo a persone del progetto.

<!-- help: calendar#how-to-create-an-event src=5f4ebe03b3 -->
## Creare un evento

1. Apri **Calendario** e tocca **Evento** (sul telefono: il pulsante +).
2. Compila **Titolo**, **Inizio** e **Termina** e, se serve, **Ripetizione**.
3. Tocca **Salva**.

Poi: l'evento è nel calendario e sul tuo telefono, se è collegato.

<!-- help: calendar#how-to-subscribe-to-another-calendar src=9f0cf2e56c -->
## Abbonarsi a un altro calendario

1. Apri **Calendario** > **Calendari** > **Abbonamenti…** (oppure **Impostazioni** > **Integrazioni** > **Calendari**).
2. Tocca **Aggiungi calendario**.
3. Incolla il link del calendario e tocca **Aggiungi**. Per un account scegli **Account CalDAV** e **Trova calendari**.

Poi: i suoi eventi compaiono nel tuo calendario, in sola lettura e solo per te.

<!-- help: calendar#how-to-show-kalmido-on-your-phone src=73923b0417 -->
## Vedere Kalmido sul telefono

1. Apri **Calendario** > **Calendari** > **Sul telefono…** (oppure **Impostazioni** > **Integrazioni** > **App calendario (CalDAV)**).
2. Tocca **Nuova password per app** e copia server, nome utente e password nelle impostazioni del calendario del telefono.

Poi: i tuoi eventi e le attività con data compaiono nel calendario del telefono. Usa lì la password per app, mai la tua
password di Kalmido.

<!-- help: wiki#how-to-write-a-knowledge-page src=122a76cda7 -->
## Scrivere una pagina di conoscenza

1. Apri **Pagine di conoscenza** nella barra laterale e tocca **Nuova pagina**.
2. Scrivi il nome della pagina in **Nome**. Una `/` crea cartelle: «Processi/Lista» finisce nella cartella *Processi*.
3. Scrivi il testo. Con `[[` colleghi un'altra pagina.

Cosa succede dopo: la pagina si salva da sola e compare nell'albero a sinistra. Sotto ogni pagina, **Collegata da** elenca
le pagine che rimandano ad essa.

<!-- help: wiki#how-to-share-a-page-read-only src=f589cec1bf -->
## Condividere una pagina in sola lettura

1. Apri la pagina, apri il suo menu (⋯) e scegli **Condividi…**.
2. Per una persona: sceglila in **Scegli una persona…** (o scrivi un indirizzo e-mail) e tocca **Aggiungi**.
3. Per chi non ha un account: scegli **Crea link pubblico**, imposta **Valido fino al** se vuoi e copia il link.

Cosa succede dopo: la persona legge questa pagina (o l'intera cartella, con *Condividi cartella…*) e nient'altro delle
tue pagine; il link apre una pagina semplice senza accesso. **Disattiva** termina un link subito.

<!-- help: wiki#how-to-bring-back-an-earlier-version-of-a-page src=f736215a16 -->
## Ripristinare una versione precedente di una pagina

1. Apri la pagina, apri il suo menu (⋯) e scegli **Cronologia**.
2. Scegli una versione nell'elenco: Kalmido mostra cosa differisce dal testo attuale.
3. Tocca **Ripristina**.

Cosa succede dopo: il vecchio testo torna a essere quello attuale come nuova versione, quindi non si perde nulla; il
ripristino si può annullare.

<!-- help: sheets#how-to-make-a-table-with-a-formula src=b8056fbeac -->
## Creare una tabella con una formula

1. Apri **Tabelle**, tocca **Nuova tabella**, dagli un nome e tocca **Crea**.
2. Tocca **Aggiungi colonna** e **Aggiungi riga** finché la griglia va bene e scrivi i valori nelle celle.
3. Inizia una cella con `=`, per esempio `=B2*C2` (ore per tariffa) o `=SOMMA(C2:C9)`.

Cosa succede dopo: la cella mostra il risultato e si ricalcola quando cambia un valore; la tabella si salva da sola.

<!-- help: sheets#how-to-share-one-table src=e19d1eba08 -->
## Condividere una tabella

1. Apri la tabella, apri il suo menu e scegli **Condividi…**.
2. Scegli una persona o un agente in **Condividi con …**, poi **Può vedere** o **Può modificare** e tocca **Aggiungi**.

Cosa succede dopo: la persona vede solo questa tabella, non il resto del tuo spazio di lavoro; la trova in **Condiviso con me**.
**Smetti di condividere** la termina subito.

<!-- help: team#how-to-write-to-a-colleague-in-the-team-chat src=d14fa10beb -->
## Scrivere a qualcuno nella chat del team

1. Apri **Chat del team** e tocca **Nuovo messaggio**.
2. Scegli la persona (o **Nuovo canale** per un canale).
3. Scrivi il messaggio e tocca **Invia**.

Cosa succede dopo: la persona riceve il messaggio e una notifica; vedi quando l'ha letto. Ogni progetto che condividi ha
anche una propria chat.

<!-- help: team#how-to-pin-a-message-or-answer-in-a-thread src=d57b9f4728 -->
## Fissare un messaggio o rispondere in un thread

1. Apri il menu di un messaggio (sul telefono: tienilo premuto).
2. Scegli **Fissa** per tenere in vista in alto un messaggio importante, oppure **Rispondi nel thread** per rispondere senza
   riempire la conversazione principale.

Cosa succede dopo: i messaggi fissati restano nella barra sopra i messaggi (al massimo cinque per conversazione); un
thread mostra le risposte a quel messaggio e i suoi partecipanti vengono avvisati.

<!-- help: budget#how-to-start-a-household-budget src=1116c1b0a8 -->
## Creare un budget domestico

1. Apri **Budget** (nell'area **Casa e vita**, da attivare in *Impostazioni > Moduli*) e tocca **Crea un budget**.
2. Tocca **Nuova voce**, compila **Importo**, la data e **Cosa**, scegli una categoria e tocca **Salva**.

Cosa succede dopo: il mese mostra cosa hai **Ricevuto** e **Speso** e cosa è **Rimane**; le categorie mostrano le spese
rispetto al piano. Ogni modifica si può annullare.

<!-- help: budget#how-to-add-rent-and-other-recurring-entries src=cd197ab4f2 -->
## Aggiungere l'affitto e altre voci ricorrenti

1. Nel budget apri il menu (⋯), scegli **Voci ricorrenti** e poi **Nuova voce ricorrente**.
2. Indica cos'è e l'importo, scegli in **Ogni quanto** mensile, trimestrale o annuale e tocca **Salva**.

Cosa succede dopo: la voce compare sotto **Da registrare questo mese** quando scade. Kalmido non la registra mai da solo: tocca
**Prenotato** quando i soldi sono davvero usciti (o entrati).

<!-- help: budget#how-to-import-a-bank-statement-into-the-budget src=45308584bc -->
## Importare un estratto conto nel budget

Kalmido non ha accesso alla tua banca: scarichi tu il file.

1. Scarica dalla tua banca l'esportazione CSV (o CAMT) dell'estratto conto.
2. Nel budget apri il menu (⋯), scegli **Importa file CSV** e il file in **Scegli file**.
3. Controlla quale colonna contiene data, importo e testo, e conferma.

Cosa succede dopo: i nuovi movimenti entrano nel budget; quelli già presenti non vengono raddoppiati. **Annulla questa importazione**
annulla tutta l'importazione.

<!-- help: home#how-to-make-a-shopping-list src=c52a018554 -->
## Creare una lista della spesa

1. Apri **Casa e vita**; senza lista offre **Lista della spesa**. Toccala.
2. Aggiungi gli articoli come scrivi un'attività; «2 l di latte» e «latte» contano come lo stesso articolo.

Cosa succede dopo: gli articoli vengono ordinati per reparto (spostane uno una volta e il successivo ci va da solo), e
chi condivide la lista spunta in diretta mentre fa la spesa.

<!-- help: home#how-to-sort-projects-into-folders src=9e6ec9656c -->
## Ordinare i progetti in cartelle

1. Nella barra laterale apri il menu (⋯) di un progetto e scegli **Sposta nella cartella…**.
2. Scegli una cartella o tocca **Nuova cartella…** e dalle un nome.

Cosa succede dopo: il progetto sta in quella cartella nella barra laterale. Puoi anche trascinare i progetti tra le
cartelle e condividere un'intera cartella in una volta (vedi «Condividere una cartella con altre persone»).

<!-- help: team#how-to-share-a-folder-with-people src=d68cfe0773 -->
## Condividere una cartella con altre persone

1. Nella barra laterale apri il menu (⋯) di una cartella e scegli **Condividi cartella…**.
2. Scegli una persona in **Condividi con …** e tocca **Aggiungi**. Per gli agenti c'è la parte **Agenti** dello stesso dialogo.

Cosa succede dopo: tutti i progetti della cartella sono condivisi con lei, anche quelli aggiunti più tardi.
**Smetti di condividere** la termina subito. Un singolo progetto si condivide allo stesso modo dal suo menu.

<!-- help: team#how-to-give-people-without-an-account-a-public-link src=5c9b76a147 -->
## Dare un link pubblico a chi non ha un account

1. Apri il dialogo **Condividi…** del progetto o della cartella e cerca **Link pubblico**.
2. Imposta **Valido fino al** se il link deve scadere, copialo con **Copia il link** e invialo.

Cosa succede dopo: chiunque abbia il link può leggere il progetto, senza accesso, in sola lettura, senza commenti,
assegnatari o file. **Disattiva** termina il link subito.
