<!-- Kalmido help, French (2.1086.0, #5820). One block per "How to" section of docs/*.md: the key and the fingerprint (src)
of the English text it was translated from. **Bold** = the label exactly as the interface shows it.
Check: python3 tools/check_userhelp.py. -->

<!-- help: files#how-to-set-up-a-scan-inbox src=b33c638618 -->
## Configurer une boîte de scans

Une boîte de scans envoie les nouveaux scans d'un dossier de ton ordinateur directement dans tes documents.

1. Ouvre **Paramètres** > **Intégrations** et va à **Documents : entrées**.
2. Sous **Surveillance de dossier**, télécharge le programme pour ton ordinateur (Mac ou Windows).
3. Ouvre **Nouvelle boîte de scans**, saisis un **Nom**, choisis le dossier sous **Dans le dossier** et touche **Créer la boîte**.
4. Kalmido affiche le **Code d’installation** une seule fois. Touche **Copier**, lance le programme, colle le code et choisis
   le dossier à surveiller.

Ensuite : chaque nouveau fichier de ce dossier est envoyé, lu et classé dans tes documents. Tu retrouves la boîte au même
endroit pour changer le dossier, la prolonger d'un an ou la révoquer. Toi seul crées une boîte de scans, jamais un agent.

<!-- help: files#how-to-add-documents-and-find-them-again src=4520b96808 -->
## Ajouter des documents et les retrouver

1. Ouvre **Fichiers** > **Documents**.
2. Touche **Ajouter des documents** et choisis des PDF ou des photos, ou dépose-les sur la page. Sur le téléphone,
   **Numériser** photographie une lettre.
3. Tape un mot dans **Rechercher dans les documents…** ; la recherche trouve aussi les mots dans les lettres.

Ensuite : Kalmido lit chaque document et remplit date, montant et expéditeur. Ce qui est incertain attend dans **À vérifier** :
ouvre-le, corrige et touche **Vérifié** (ou **Tout accepter** pour les suggestions).

<!-- help: files#how-to-share-a-folder src=f6f99fa88e -->
## Partager un dossier

1. Ouvre **Fichiers** et le menu **Plus** (⋯) du dossier, puis **Partager…**.
2. Sous **Partager avec…** choisis une personne, un groupe ou un agent.
3. Choisis **Peut consulter** ou **Peut modifier**, touche **Ajouter** puis **Terminé**.

Ensuite : la personne voit le dossier et tout son contenu, aussi ce qui sera ajouté plus tard. Seul le propriétaire peut
partager un dossier.

<!-- help: agent-setup#how-to-create-your-personal-agent src=55f8406267 -->
## Créer ton agent personnel

Un agent est un assistant (par exemple Claude) qui travaille dans Kalmido avec son propre compte et ne voit que ce que tu
partages avec lui.

1. Ouvre **Paramètres** > **Agents** et l'onglet **Configurer**.
2. Sous **Tes agents personnels**, remplis **Nom affiché** et les deux autres champs, puis touche **Créer l'agent**.
3. Dans la fenêtre qui s'ouvre, choisis ton **Ordinateur** et le **Dossier du projet**, puis touche **Créer la commande**.
4. Touche **Copier**, ouvre le Terminal sur cet ordinateur, colle la commande et appuie sur Entrée. Puis **Terminé**.

Ensuite : l'agent apparaît sous **Tes agents personnels**. Il ne voit encore rien : donne-lui un projet ou un dossier. La
commande ne sert qu'une fois et quelques minutes ; **Configurer** dans la ligne de l'agent en crée une nouvelle.

<!-- help: agent-setup#how-to-give-an-agent-access-to-a-project-or-folder src=aaf357fa82 -->
## Donner à un agent l'accès à un projet ou un dossier

Un projet :

1. Ouvre le menu (⋯) du projet et choisis **Agent…**.
2. Sous **Agents**, choisis l'agent et confirme avec **Partager**.

Un dossier dans Fichiers ou Connaissances :

1. Ouvre le menu (⋯) du dossier et choisis **Partager…**.
2. Sous **Partager avec…** choisis l'agent, **Peut consulter** ou **Peut modifier**, touche **Ajouter** puis **Terminé**.

Ensuite : l'agent travaille dans ce projet ou ce dossier, et seulement là. Chaque accès d'un agent figure dans l'historique ;
un dossier verrouillé n'est jamais partagé avec un agent.

<!-- help: agent-setup#how-to-approve-what-an-agent-asks-for src=dfbe19a2e9 -->
## Approuver ce que demande un agent

1. Quand un agent a besoin de ton accord, une carte « … t'attend » apparaît (dans Aujourd'hui et dans Agents).
2. Touche **Approuver** ou **Refuser**. Pour une proposition, d'abord **Examiner la proposition**.

Ensuite : l'agent continue avec ce que tu as approuvé ; une étape refusée n'a pas lieu.

<!-- help: office#how-to-write-a-quotation src=c3eae76ef0 -->
## Rédiger un devis

1. Ouvre **Bureau** > **Devis** et touche **Nouveau devis**. Le brouillon s'ouvre aussitôt.
2. Choisis le **Client**.
3. Ajoute des lignes avec **Ajouter une prestation**.
4. Quand tout est prêt, touche **Figer**. Ensuite numéro, lignes et montants ne changent plus.
5. Touche **Envoyer** pour l'envoyer par e-mail, ou **Télécharger le PDF**.

Ensuite : le devis est dans la liste. Marque-le comme envoyé, puis comme **Accepté** ou refusé ; d'un devis accepté, la
facture naît en une étape. Un brouillon se regarde avec **Aperçu**.

<!-- help: office#how-to-turn-a-quotation-into-an-invoice src=faeae491ab -->
## Transformer un devis en facture

1. Ouvre le devis accepté et touche **Créer une facture**.
2. Choisis le **Type de facture** et confirme.
3. Vérifie la facture, touche **Figer** puis **Envoyer**.

Une facture sans devis : **Bureau** > **Factures** > **Nouvelle facture**.

Ensuite : la facture reçoit son numéro en étant figée, sans trou. Elle reste ouverte jusqu'à ce qu'un paiement soit saisi.

<!-- help: office#how-to-record-a-payment src=6663fe7a8c -->
## Saisir un paiement

1. Ouvre la facture figée et touche **Saisir un paiement**.
2. Vérifie la date et le montant et touche **Saisir**.

Ou avec le relevé : **Bureau** > **Banque** > **Importer un relevé bancaire**, puis **Reprendre** la suggestion.

Ensuite : la facture est payée (ou payée en partie). Seul un administrateur de l'organisation saisit les paiements.

<!-- help: tasks#how-to-add-a-task-with-a-date src=8a3685b666 -->
## Ajouter une tâche avec une date

1. Touche **Ajouter une tâche…** en bas du projet (sur le téléphone : le bouton +).
2. Écris la tâche comme tu la penses, par exemple « Appeler le dentiste demain 15h », ou choisis la date.
3. Appuie sur Entrée.

Ensuite : la tâche arrive dans le projet ouvert (ou dans le **Panier**) avec sa date et apparaît ce jour-là dans
**Aujourd'hui**. Pour changer la date, ouvre la tâche et touche sa date : **Aujourd'hui**, **Demain**, **Semaine prochaine**
ou un jour du calendrier.

<!-- help: tasks#how-to-make-a-task-repeat src=b22f5f0a3c -->
## Répéter une tâche

Une tâche récurrente revient toute seule : chaque jour, chaque semaine ou selon ta propre règle.

1. Ouvre la tâche et touche sa date.
2. Choisis sous **Répétition**, par exemple **Tous les jours**, ou **Personnalisé…** pour ta propre règle.
3. Touche **Terminé**.

Ensuite : quand tu termines la tâche, la suivante apparaît avec la prochaine date.

<!-- help: tasks#how-to-assign-a-task-or-share-a-project src=d8a87df384 -->
## Attribuer une tâche ou partager un projet

1. Partager le projet : son menu (⋯) > **Partager…**, choisis la personne sous **Partager avec…**, un rôle (par exemple
   **Membre**) et touche **Ajouter**.
2. Attribuer une tâche : ouvre la tâche, touche **Attribuer** et choisis la personne.

Ensuite : la personne voit le projet et reçoit la tâche. On ne peut attribuer qu'aux personnes du projet.

<!-- help: calendar#how-to-create-an-event src=5f4ebe03b3 -->
## Créer un événement

1. Ouvre **Calendrier** et touche **Événement** (sur le téléphone : le bouton +).
2. Remplis **Titre**, **Début** et **Fin** et, si besoin, **Répétition**.
3. Touche **Enregistrer**.

Ensuite : l'événement est dans le calendrier et sur ton téléphone, s'il est connecté.

<!-- help: calendar#how-to-subscribe-to-another-calendar src=9f0cf2e56c -->
## S'abonner à un autre calendrier

1. Ouvre **Calendrier** > **Calendriers** > **Abonnements…** (ou **Paramètres** > **Intégrations** > **Calendriers**).
2. Touche **Ajouter un calendrier**.
3. Colle le lien du calendrier et touche **Ajouter**. Pour un compte, choisis **Compte CalDAV** et **Rechercher des calendriers**.

Ensuite : ses événements apparaissent dans ton calendrier, en lecture seule et pour toi seul.

<!-- help: calendar#how-to-show-kalmido-on-your-phone src=73923b0417 -->
## Voir Kalmido sur le téléphone

1. Ouvre **Calendrier** > **Calendriers** > **Sur le téléphone…** (ou **Paramètres** > **Intégrations** > **Apps de calendrier (CalDAV)**).
2. Touche **Nouveau mot de passe d'application** et copie serveur, nom d'utilisateur et mot de passe dans les réglages de
   calendrier du téléphone.

Ensuite : tes événements et tâches datées apparaissent dans le calendrier du téléphone. Utilise-y le mot de passe
d'application, jamais ton mot de passe Kalmido.

<!-- help: wiki#how-to-write-a-knowledge-page src=122a76cda7 -->
## Écrire une page de connaissances

1. Ouvre **Pages de connaissances** dans la barre latérale et touche **Nouvelle page**.
2. Saisis le nom de la page dans **Nom**. Un `/` crée des dossiers : « Processus/Liste » arrive dans le dossier *Processus*.
3. Écris le texte. Avec `[[`, tu relies une autre page.

Ce qui se passe ensuite : la page s'enregistre toute seule et apparaît dans l'arborescence à gauche. Sous chaque page,
**Liée depuis** liste les pages qui y renvoient.

<!-- help: wiki#how-to-share-a-page-read-only src=f589cec1bf -->
## Partager une page en lecture seule

1. Ouvre la page, ouvre son menu (⋯) et choisis **Partager…**.
2. Pour une personne : choisis-la sous **Choisir une personne…** (ou saisis une adresse e-mail) et touche **Ajouter**.
3. Pour qui n'a pas de compte : choisis **Créer un lien public**, règle **Valide jusqu'au** si tu veux et copie le lien.

Ce qui se passe ensuite : la personne lit cette page (ou tout le dossier, avec *Partager le dossier…*) et rien d'autre de
tes pages ; le lien ouvre une page simple sans connexion. **Désactiver** met fin à un lien aussitôt.

<!-- help: wiki#how-to-bring-back-an-earlier-version-of-a-page src=f736215a16 -->
## Retrouver une version antérieure d'une page

1. Ouvre la page, ouvre son menu (⋯) et choisis **Historique**.
2. Choisis une version dans la liste : Kalmido montre ce qui diffère du texte actuel.
3. Touche **Restaurer**.

Ce qui se passe ensuite : l'ancien texte redevient le texte actuel comme nouvelle version, rien n'est donc perdu ; la
restauration peut être annulée.

<!-- help: sheets#how-to-make-a-table-with-a-formula src=b8056fbeac -->
## Créer un tableau avec une formule

1. Ouvre **Tableaux**, touche **Nouveau tableau**, donne un nom et touche **Créer**.
2. Touche **Ajouter une colonne** et **Ajouter une ligne** jusqu'à ce que la grille convienne et saisis les valeurs dans les cellules.
3. Commence une cellule par `=`, par exemple `=B2*C2` (heures fois tarif) ou `=SOMME(C2:C9)`.

Ce qui se passe ensuite : la cellule affiche le résultat et se recalcule quand une valeur change ; le tableau s'enregistre tout seul.

<!-- help: sheets#how-to-share-one-table src=e19d1eba08 -->
## Partager un tableau

1. Ouvre le tableau, ouvre son menu et choisis **Partager…**.
2. Choisis une personne ou un agent sous **Partager avec…**, puis **Peut consulter** ou **Peut modifier** et touche **Ajouter**.

Ce qui se passe ensuite : la personne ne voit que ce tableau, pas le reste de ton espace de travail ; elle le trouve sous
**Partagé avec moi**. **Arrêter le partage** y met fin aussitôt.

<!-- help: team#how-to-write-to-a-colleague-in-the-team-chat src=d14fa10beb -->
## Écrire à quelqu'un dans le chat d'équipe

1. Ouvre **Chat d'équipe** et touche **Nouveau message**.
2. Choisis la personne (ou **Nouveau canal** pour un canal).
3. Écris ton message et touche **Envoyer**.

Ce qui se passe ensuite : la personne reçoit le message et une notification ; tu vois quand elle l'a lu. Chaque projet que
tu partages a aussi son propre chat.

<!-- help: team#how-to-pin-a-message-or-answer-in-a-thread src=d57b9f4728 -->
## Épingler un message ou répondre dans un fil

1. Ouvre le menu d'un message (sur le téléphone : appui long).
2. Choisis **Épingler** pour garder un message important en vue en haut de la conversation, ou **Répondre dans le fil** pour répondre
   sans remplir la conversation principale.

Ce qui se passe ensuite : les messages épinglés restent dans la barre au-dessus des messages (cinq au plus par
conversation) ; un fil montre les réponses à ce message et ses participants sont prévenus.

<!-- help: team#how-to-invite-someone-without-an-account-by-a-link src=0b47d08909 -->
## Inviter par un lien quelqu'un sans compte

1. Dans Paramètres > Compte, choisis **Trouver une personne …**.
2. Choisis **Inviter par lien**, indique si tu veux pour qui il est (visible par toi seul) et choisis **Créer le lien**.
3. Envoie le lien avec **Copier** ou **Partager**, ou laisse la personne scanner le code QR.

Ce qui se passe ensuite : qui ouvre le lien crée un compte avec son nom et son adresse e-mail et est aussitôt connecté avec
toi ; tu reçois une notification. Le lien fonctionne une fois et pendant 14 jours et n'est affiché que juste après sa
création ; **Retirer** met fin aussitôt à un lien ouvert. Qui a déjà un compte l'ouvre connecté et confirme la connexion. Un
admin du serveur peut désactiver ces liens (Paramètres > Serveur > Connexion).

<!-- help: budget#how-to-start-a-household-budget src=1116c1b0a8 -->
## Créer un budget du foyer

1. Ouvre **Budget** (dans le domaine **Maison & vie**, à activer sous *Réglages > Modules*) et touche **Créer un budget**.
2. Touche **Nouvelle opération**, remplis **Montant**, la date et **Quoi**, choisis une catégorie et touche **Enregistrer**.

Ce qui se passe ensuite : le mois montre ce que tu as **Reçu** et **Dépensé** et ce qui est **Reste** ; les catégories
montrent les dépenses face au plan. Chaque modification peut être annulée.

<!-- help: budget#how-to-add-rent-and-other-recurring-entries src=cd197ab4f2 -->
## Ajouter le loyer et d'autres opérations récurrentes

1. Dans le budget, ouvre le menu (⋯), choisis **Opérations récurrentes** puis **Nouvelle opération récurrente**.
2. Indique ce que c'est et le montant, choisis dans **À quelle fréquence** mensuel, trimestriel ou annuel et touche **Enregistrer**.

Ce qui se passe ensuite : l'opération apparaît sous **À enregistrer ce mois-ci** dès qu'elle est due. Kalmido ne la comptabilise
jamais tout seul : touche **Réservé** quand l'argent est vraiment parti (ou arrivé).

<!-- help: budget#how-to-import-a-bank-statement-into-the-budget src=45308584bc -->
## Importer un relevé bancaire dans le budget

Kalmido n'a pas accès à ta banque : tu télécharges le fichier toi-même.

1. Télécharge chez ta banque l'export CSV (ou CAMT) de ton relevé de compte.
2. Dans le budget, ouvre le menu (⋯), choisis **Importer un fichier CSV** et le fichier sous **Choisir des fichiers**.
3. Vérifie quelle colonne contient la date, le montant et le texte, puis confirme.

Ce qui se passe ensuite : les nouvelles opérations arrivent dans le budget ; celles qui y sont déjà ne sont pas doublées.
**Annuler cet import** annule tout l'import.

<!-- help: home#how-to-make-a-shopping-list src=c52a018554 -->
## Créer une liste de courses

1. Ouvre **Maison & vie** ; sans liste, il propose **Liste de courses**. Touche-le.
2. Ajoute des articles comme tu saisis une tâche ; « 2 l de lait » et « lait » comptent comme le même article.

Ce qui se passe ensuite : les articles sont triés par rayons (déplace-en un une fois et le suivant y va tout seul), et
les personnes avec qui tu partages la liste cochent en direct pendant les courses.

<!-- help: home#how-to-sort-projects-into-folders src=9e6ec9656c -->
## Ranger des projets dans des dossiers

1. Dans la barre latérale, ouvre le menu (⋯) d'un projet et choisis **Déplacer vers un dossier…**.
2. Choisis un dossier ou touche **Nouveau dossier…** et donne-lui un nom.

Ce qui se passe ensuite : le projet se trouve dans ce dossier de la barre latérale. Tu peux aussi faire glisser des
projets entre dossiers et partager un dossier entier d'un coup (voir « Partager un dossier avec des personnes »).

<!-- help: team#how-to-share-a-folder-with-people src=d68cfe0773 -->
## Partager un dossier avec des personnes

1. Dans la barre latérale, ouvre le menu (⋯) d'un dossier et choisis **Partager le dossier…**.
2. Choisis une personne sous **Partager avec…** et touche **Ajouter**. Pour les agents, la partie **Agents** du même dialogue.

Ce qui se passe ensuite : tous les projets du dossier sont partagés avec elle, y compris ceux que tu ajoutes plus tard.
**Arrêter le partage** y met fin aussitôt. Un projet seul se partage de la même façon depuis son propre menu.

<!-- help: team#how-to-give-people-without-an-account-a-public-link src=5c9b76a147 -->
## Donner un lien public à des personnes sans compte

1. Ouvre le dialogue **Partager…** du projet ou du dossier et cherche **Lien public**.
2. Règle **Valide jusqu'au** si le lien doit expirer, copie-le avec **Copier le lien** et envoie-le.

Ce qui se passe ensuite : quiconque a le lien peut lire le projet, sans connexion, en lecture seule, sans commentaires,
responsables ni fichiers. **Désactiver** met fin au lien aussitôt.
