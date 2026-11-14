# 3CX pour Dokos / ERPNext

Intégration de la téléphonie 3CX avec l'ERP.

| Fonction | Comment | Version / licence 3CX |
|---|---|---|
| Nom (et société) de l'appelant affiché dans 3CX | Template CRM, recherche par numéro (Contacts + Prospects) | V18, V20 (Pro / Enterprise) |
| Ouverture de la fiche ERP depuis 3CX | `ContactUrl` → fiche Contact (ou Client/Fournisseur lié) | V18, V20 |
| Recherche de contacts ERP depuis le client 3CX | Scénario `SearchContacts` | V20 |
| Création d'un contact ERP depuis 3CX | Scénario `CreateContactRecordFromClient` | V18, V20 |
| Journal d'appels dans l'ERP (timeline Contact / Prospect / Client) | Scénario `ReportCall` → doctype `Call Log` d'ERPNext | V18, V20 |
| Transcription, résumé IA, lien d'enregistrement | Variables `Transcription`, `Summary`, `RecordingUrl` de `ReportCall` | V20 avec transcription activée |
| Conversations live chat / SMS / WhatsApp | Scénario `ReportChat` → `Communication` (canal Chat) | V18, V20 |
| Notification d'appel entrant dans l'ERP | Déclenchée par la recherche du numéro | V18, V20 |
| Click-to-call depuis tous les champs téléphone | Lien `tel:` (application ou extension navigateur 3CX) | Toutes |
| Click-to-call piloté par le PBX | API Call Control `makecall` | V20 Enterprise (8SC+) |
| Import de tout l'historique (y compris numéros inconnus) + score de sentiment | API de configuration (XAPI), toutes les 15 min | V20 Enterprise (8SC+) |
| Écoute des enregistrements depuis l'ERP, demande de transcription | XAPI `Recordings` | V20 Enterprise (8SC+) |

## Installation

```bash
bench get-app https://github.com/gauthierdc/threecx
bench --site <site> install-app threecx
bench build --app threecx
bench restart
```

L'installation crée :
- le doctype **Paramètres 3CX** (`ThreeCX Settings`) ;
- des champs 3CX sur **Call Log** (poste, agent, file, transcription, sentiment, enregistrement…) et sur **Utilisateur** (poste 3CX, notification des appels entrants) ;
- le rôle **3CX Integration**.

## Configuration

### 1. Utilisateur technique ERP

1. Créer un utilisateur (ex. `3cx@mondomaine.fr`) avec le rôle **3CX Integration** uniquement.
2. Fiche utilisateur > Paramètres > Clés API > **Générer les clés** : noter l'API Key et l'API Secret.

### 2. Paramètres 3CX dans l'ERP

Renseigner l'URL de l'ERP (joignable par le serveur 3CX et par les postes), la version 3CX, puis cocher **Activé**.

### 3. Template CRM dans 3CX

1. Paramètres 3CX > **Télécharger le template 3CX** (`dokos-erp-3cx.xml`).
2. Console 3CX > Paramètres > CRM Integration > onglet *Server Side* : importer le template (« Add »), puis le sélectionner.
3. Saisir l'URL de l'ERP, l'API Key et l'API Secret de l'utilisateur technique, puis **Test** avec un numéro connu.
4. Côté postes (client web 3CX > Paramètres > Intégrations) : régler l'ouverture automatique de la fiche contact à la réponse si souhaité.

Les options de recherche, de journalisation et le choix de la fiche ouverte sont lus à chaque requête : pas besoin de réimporter le template quand on les modifie. Il faut le régénérer seulement en changeant de version 3CX (V18 ↔ V20).

> 3CX n'appelle en général la journalisation que pour les appels dont le correspondant a été identifié. Pour garder la trace des numéros inconnus, activer la synchronisation XAPI.

### 4. API 3CX (V20 Enterprise, facultatif)

Console 3CX > Intégrations > API > Ajouter : cocher l'accès à l'**API de configuration** (synchro, enregistrements) et/ou à **Call Control** (click-to-call), avec les postes à piloter. Reporter le Client ID et la clé API dans les Paramètres 3CX, puis **API 3CX > Tester la connexion**.

Si l'API répond 403, donner au client API le rôle *System Owner* sur le département de l'instance (souvent `DEFAULT`).

### 5. Utilisateurs

Dans chaque fiche Utilisateur : **Poste 3CX** (attribution des appels, click-to-call par API) et **Notification des appels entrants 3CX**.

## Points à valider sur votre PBX

L'API XAPI n'a pas de documentation publique complète : la synchronisation s'appuie sur le schéma OpenAPI publié par 3CX (`3cx/xapi-tutorial`). À la première activation, lancer **Synchroniser l'historique maintenant** et vérifier le compte rendu (lignes lues / synchronisées / ignorées) ; les lignes en erreur sont dans le *Journal des erreurs* avec leur contenu brut.

## Tests

```bash
bench --site <site> run-tests --app threecx
```
