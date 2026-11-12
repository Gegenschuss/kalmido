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
