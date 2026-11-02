"""2.449.0 (#3768): the samples in French, translated when they were built (Kalmido never calls a language model). Same keys,
variables and [[optional parts]] as the English samples; the legal samples say on their second line that the translation
must be checked. SAMPLES = doctpl.DT_STARTERS + doctpl_samples.DMA_SAMPLES, BLOCKS = lettermail.LTB_STARTERS."""

SAMPLES = {
    "contract": ("Contrat de prestation de services", """# Contrat de prestation de services

Entre {{company.name}}[[, {{company.address}}]] (le prestataire)
et {{client.name}}[[, {{client.address}}]] (le client)

## 1. Objet
Le prestataire fournit des services au client[[ dans le cadre du projet {{project.title}}]][[ selon le devis {{offer.number}}]][[ du {{offer.date}}]].

## 2. Rémunération
La rémunération est fixée par le devis[[ et s'élève à {{offer.net}} hors TVA]]. Les factures sont payables sous {{payment.days}} jours sans escompte.

## 3. Collaboration
Le client fournit en temps utile les documents et informations nécessaires.[[ Interlocuteur chez le client : {{client.contact}}.]]

## 4. Droits d'utilisation
Les droits d'utilisation sont transférés dans l'étendue convenue après paiement intégral.

## 5. Dispositions finales
Toute modification ou tout ajout doit être fait par écrit. Si une clause est invalide, le reste du contrat demeure valable.

Date : {{today}}"""),
    "confirmation": ("Confirmation de commande", """# Confirmation de commande

Madame, Monsieur,

nous vous remercions de votre commande. Nous confirmons la commande[[ selon notre devis {{offer.number}}]][[ du {{offer.date}}]][[ pour le projet {{project.title}}]].

- Client : {{client.name}}
- Interlocuteur : {{client.contact}}
- Montant de la commande : {{offer.net}} hors TVA

Les conditions du devis s'appliquent. Veuillez vérifier ces informations et nous prévenir si quelque chose ne convient pas.

Cordialement,
{{company.name}}"""),
    "nda": ("Accord de confidentialité", """# Accord de confidentialité

[Traduction automatique, à vérifier avant utilisation : supprimez ensuite cette ligne.]

Entre {{company.name}}[[, {{company.address}}]]
et {{client.name}}[[, {{client.address}}]]

## 1. Informations confidentielles
Sont confidentielles toutes les informations qu'une partie communique à l'autre dans le cadre de la collaboration[[ sur le projet {{project.title}}]] et qui sont désignées comme confidentielles ou reconnaissables comme telles.

## 2. Obligations
Les parties utilisent les informations confidentielles uniquement pour le projet, ne les transmettent pas à des tiers et les protègent avec un soin raisonnable.

## 3. Exceptions
Ces obligations ne s'appliquent pas aux informations qui sont publiques, qu'une partie connaissait déjà légitimement ou qu'elle doit divulguer en vertu de la loi.

## 4. Durée
Le présent accord s'applique à compter du {{today}} et prend fin trois ans après la fin de la collaboration."""),
    "letter": ("Lettre d'accompagnement", """# [Objet]

Madame, Monsieur,

[Votre texte]

N'hésitez pas à nous contacter pour toute question.

Cordialement,
{{company.name}}"""),
    "reminder": ("Rappel de paiement", """# Rappel de paiement

Madame, Monsieur,

cela a peut-être échappé à votre attention : nous n'avons pas encore reçu le paiement de la facture [numéro de facture] du [date de facture] d'un montant de [montant].

Merci de virer le montant dû d'ici le [date] sur le compte indiqué sur la facture. Si vous avez payé entre-temps, veuillez ne pas tenir compte de ce courrier.

Cordialement,
{{company.name}}"""),
    "dunning": ("Mise en demeure", """# Mise en demeure

Madame, Monsieur,

malgré notre rappel de paiement du [date du rappel], la facture [numéro de facture] du [date de facture] d'un montant de [montant] reste impayée.

Merci de régler le montant dû au plus tard le [échéance]. Passé ce délai, nous nous réservons le droit d'engager d'autres démarches.

Si vous avez payé entre-temps, veuillez ne pas tenir compte de ce courrier.

Cordialement,
{{company.name}}"""),
    "termination": ("Résiliation", """# Résiliation du contrat [contrat / numéro de contrat]

Madame, Monsieur,

par la présente, nous résilions le contrat mentionné ci-dessus dans le respect du préavis, avec effet au [date], ou à défaut à la prochaine date possible.

Merci de nous confirmer par écrit la réception de cette résiliation et la date de fin du contrat.

Cordialement,
{{company.name}}

{{today}}"""),
    "authority": ("Procuration", """# Procuration

{{client.name}}
{{client.address}}

donne par la présente pouvoir à

{{company.name}}
{{company.address}}

d'accomplir les actes suivants au nom du mandant dans le cadre du projet {{project.title}} :

- [acte 1]
- [acte 2]

Cette procuration est valable du {{today}} au [date] et peut être révoquée à tout moment. La sous-délégation [n']est [pas] autorisée."""),
    "handover": ("Procès-verbal de remise", """# Procès-verbal de remise

Projet : {{project.title}}
Remise de {{company.name}} à {{client.name}}
Interlocuteur : {{client.contact}}
Date : {{today}}

## Éléments remis
- [objet / livraison 1]
- [objet / livraison 2]

## État et remarques
[état, pièces manquantes, points ouverts]

## Confirmation
Le client confirme avoir reçu les prestations mentionnées ci-dessus dans l'état décrit."""),
    "credit": ("Lettre d'accompagnement de l'avoir", """# Votre avoir [numéro d'avoir]

Madame, Monsieur,

veuillez trouver ci-joint notre avoir [numéro d'avoir] du {{today}} d'un montant de [montant] sur la facture [numéro de facture] du projet {{project.title}}.

Nous [virerons le montant sur votre compte d'ici la date / imputerons le montant sur la prochaine facture].

Cordialement,
{{company.name}}"""),
    "privacy_dpa": ("Contrat de sous-traitance de données", """# Contrat de sous-traitance de données

[Texte type, pas un conseil juridique. Traduction automatique, à vérifier avant utilisation : adaptez-le à la mission et supprimez cette ligne.]

Entre {{client.name}}, {{client.address}} (responsable du traitement)
et {{company.name}}, {{company.address}} (sous-traitant)

## 1. Objet et durée
Le sous-traitant traite des données à caractère personnel pour le compte du responsable du traitement pour les prestations suivantes : [prestations]. La durée suit celle de la mission sous-jacente.

## 2. Nature et finalité du traitement
[nature et finalité, p. ex. stockage, maintenance, analyse]

## 3. Types de données et personnes concernées
- Types de données à caractère personnel : [p. ex. coordonnées, données contractuelles]
- Catégories de personnes concernées : [p. ex. clients, salariés]

## 4. Instructions
Le sous-traitant ne traite les données que sur instruction documentée du responsable du traitement (art. 28, paragraphe 3, point a), du RGPD).

## 5. Confidentialité
Les personnes autorisées à traiter les données sont tenues à la confidentialité (art. 28, paragraphe 3, point b), du RGPD).

## 6. Sécurité du traitement
Le sous-traitant prend les mesures techniques et organisationnelles prévues à l'art. 32 du RGPD : [mesures ou annexe].

## 7. Sous-traitants ultérieurs
Il n'est fait appel à d'autres sous-traitants qu'avec l'autorisation préalable du responsable du traitement (art. 28, paragraphes 2 et 4, du RGPD). Actuellement : [aucun / liste].

## 8. Assistance
Le sous-traitant aide le responsable du traitement à répondre aux demandes des personnes concernées et à respecter les obligations des art. 32 à 36 du RGPD (art. 28, paragraphe 3, points e) et f), du RGPD).

## 9. Suppression et restitution
À la fin des prestations, les données sont supprimées ou restituées au choix du responsable du traitement, sauf obligation légale de conservation (art. 28, paragraphe 3, point g), du RGPD).

## 10. Preuves et audits
Le sous-traitant met à disposition les informations nécessaires pour démontrer le respect de ses obligations et permet la réalisation d'audits (art. 28, paragraphe 3, point h), du RGPD).

## 11. Notification des violations
Le sous-traitant notifie toute violation de données à caractère personnel dans les meilleurs délais après en avoir pris connaissance (art. 33, paragraphe 2, du RGPD).

Date : {{today}}"""),
    "privacy_info": ("Informations sur la protection des données", """# Informations sur la protection des données

[Texte type, pas un conseil juridique. Traduction automatique, à vérifier avant utilisation : complétez-le et supprimez cette ligne.]

Informations au titre des art. 13 et 14 du RGPD pour {{client.name}}

## 1. Responsable du traitement
{{company.name}}, {{company.address}}

## 2. Finalités et bases juridiques
Nous traitons vos données pour préparer et exécuter un contrat avec vous (art. 6, paragraphe 1, point b), du RGPD), pour respecter des obligations légales telles que les obligations de conservation (art. 6, paragraphe 1, point c), du RGPD) et lorsque vous y avez consenti (art. 6, paragraphe 1, point a), du RGPD).

## 3. Catégories de données
[p. ex. nom, adresse, coordonnées, données contractuelles et de facturation]

## 4. Destinataires
[p. ex. expert-comptable, hébergeur en tant que sous-traitant]

## 5. Transferts vers des pays tiers
[aucun / précisions]

## 6. Durée de conservation
Nous conservons vos données aussi longtemps que nécessaire à ces finalités et au-delà lorsque des durées légales de conservation s'appliquent : [durées].

## 7. Vos droits
- Accès, rectification, effacement et limitation du traitement (art. 15 à 18 du RGPD)
- Portabilité des données (art. 20 du RGPD) et opposition (art. 21 du RGPD)
- Retrait d'un consentement à tout moment pour l'avenir (art. 7, paragraphe 3, du RGPD)
- Réclamation auprès d'une autorité de contrôle de la protection des données (art. 77 du RGPD)

## 8. Fourniture des données
Nous avons besoin des données nécessaires au contrat pour le conclure et l'exécuter. [délégué à la protection des données, s'il a été désigné]

État au : {{today}}"""),
    "privacy_consent": ("Consentement au traitement des données", """# Consentement au traitement des données

[Texte type, pas un conseil juridique. Traduction automatique, à vérifier avant utilisation : adaptez-le et supprimez cette ligne.]

{{client.name}}, représenté par {{client.contact}}, consent à ce que {{company.name}} traite les données à caractère personnel suivantes :

- Données : [données]
- Finalité : [finalité]

## Caractère volontaire et retrait
Le consentement est volontaire. Il peut être retiré à tout moment sans motif pour l'avenir (art. 7, paragraphe 3, du RGPD), par exemple par e-mail à [adresse e-mail]. Le retrait ne remet pas en cause la licéité du traitement effectué avant celui-ci.

Vous trouverez plus d'informations dans nos informations sur la protection des données.

Date : {{today}}"""),
}

BLOCKS = {
    "cancel": ("Résiliation", "par la présente, je résilie le contrat mentionné ci-dessus dans le respect du préavis, à la prochaine date possible. "
                              "Merci de me confirmer par écrit la résiliation et la date à laquelle elle prend effet."),
    "objection": ("Opposition", "par la présente, je forme opposition à votre décision du [date], référence [référence]. Je vous communiquerai "
                                "les motifs séparément. Merci de me confirmer la réception de ce courrier."),
    "reminder": ("Rappel de paiement", "cela a peut-être échappé à votre attention : le montant de [montant] de notre facture [numéro] du [date] "
                                       "reste dû. Merci de le virer d'ici le [date]. Si vous avez déjà payé, veuillez ne pas tenir compte de ce courrier."),
    "extension": ("Demande de prolongation de délai", "je vous prie de bien vouloir prolonger le délai du [date] jusqu'au [date], car certains documents "
                                                      "me manquent encore. Je vous remercie de votre compréhension."),
}
