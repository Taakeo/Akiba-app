# AKIBA APP

Application de gestion (ventes, achats, stocks, caisse...) pour l'association Akiba.
Spécification complète : `Contenu/AKIBA_APP_Specifications_v2.md` (dossier de
travail local, non versionné — voir `.gitignore`).

## Démarrage (développement)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
# éditer .env : FLASK_SECRET_KEY, DB_ENCRYPTION_KEY

flask --app run.py seed-db   # profils par défaut, compte Administrateur (PIN 0000),
                              # comptes financiers, catalogue de démonstration
python run.py                 # http://127.0.0.1:5000
```

## CSS (Tailwind CLI v4, sans Node)

Le binaire standalone `tools/tailwindcss.exe` (non versionné, ~110 Mo — à
retélécharger si besoin depuis les releases GitHub tailwindlabs/tailwindcss)
compile `app/static/src/input.css` vers `app/static/dist/output.css` (non
versionné, à regénérer après tout changement de template ou de token de
design — les tokens sont définis en CSS natif via `@theme` dans
`input.css`, pas dans un `tailwind.config.js`, car le binaire installé est
Tailwind v4) :

```bash
tools\tailwindcss.exe -i app/static/src/input.css -o app/static/dist/output.css --minify
```

Le JS du Point de Vente (`app/static/js/pos.js`) est vanilla JS, servi tel
quel, sans étape de build.

## Tests

```bash
pytest
```

## État actuel

- App factory Flask (`app/__init__.py`), config via `.env` (`config.py`),
  base SQLite chiffrée via SQLCipher (vérifié : illisible avec `sqlite3` nu).
- Modèle Profil / Sous-profil (`app/models/user.py`) avec PIN, suspension,
  traçabilité — §3 de la spec.
- Authentification par PIN en 3 écrans (sélection profil → sous-profil → PIN).
- Catalogue (`app/models/catalogue.py`) : Poste, Projet, Catégorie,
  Sous-catégorie, Produit, tarifs multiples par produit — §4.3, §5.1.
- Finance (`app/models/finance.py`) : Comptes financiers, Moyens de paiement,
  Session de caisse, Mouvements — §7.
- Ventes (`app/models/ventes.py`) : Vente, LigneVente (snapshot hiérarchie
  comptable), VentePaiement (paiement multiple) — §6, §7.6.
- Blueprint `caisse` : ouverture (fond de caisse), fermeture (calcul
  recettes/dépenses/théorique/écart), entrées-sorties manuelles — §7.2-7.3.
- Blueprint `pos` : 3 zones (catégories / grille produits / ticket),
  sélection de tarif, panier JS, encaissement multi-moyens de paiement,
  décrément de stock, reçu imprimable (`window.print()`) — §6.
  Les prix sont **toujours recalculés côté serveur** à partir de la fiche
  produit et du tarif sélectionné, jamais acceptés depuis le client.
- Blueprint `admin` (§4.1, permission `admin`, réservé à l'Administrateur) :
  CRUD Postes / Projets / Catégories / Sous-catégories (archivage, jamais de
  suppression définitive — §13), CRUD Produits avec tarifs multiples, gestion
  des sous-profils (création + PIN, suspension/réactivation, reset PIN).
  Plus aucun module ne dépend des données de seed pour fonctionner.
- Tableau de bord minimal, layout partagé authentifié (`_app_shell.html`).
- Design system "Earth & Hearth" en tokens CSS natifs Tailwind v4.
- Interface calée pour poste fixe tactile 13" 1920×1080 (nav icône fixe,
  cibles tactiles ≥ 48px, grille produits en container queries — voir
  `app/templates/pos/index.html`).
- Polices Quicksand / Plus Jakarta Sans / Material Symbols Outlined
  vendorisées dans `app/static/vendor/fonts/` (pas de CDN, conforme §2.1).
- Fournisseurs (`app/models/fournisseur.py`) : fiche (coordonnées), CRUD
  admin, rattachement en fournisseur principal sur la fiche produit — §5.3.
- Achats (`app/models/achat.py`, blueprint `achats`) : achat de stock
  (augmente le stock + mouvement tracé) vs dépense générale (aucun effet
  stock, rattachée à poste/catégorie), pièces jointes (facture/devis/photo/BL)
  stockées sur disque sous `instance/uploads/achats/`, jamais en BLOB — §8.
- Stocks (`app/models/stock.py`, blueprint `stocks`) : grand livre des
  mouvements (`MouvementStock`, tous motifs §9.2), état du stock avec
  alertes rupture/seuil, ajustement manuel (perte/don/consommation
  interne/correction), inventaires général/catégorie/produit avec calcul
  théorique/réel/écart et correction automatique à la clôture — §9.
  Le Point de Vente et les Achats de stock alimentent ce même grand livre
  (`enregistrer_mouvement`), donc toute variation de stock est tracée
  quelle que soit son origine.
- Tableau de bord réel (`app/main/routes.py`) : CA du jour/mois, nombre de
  ventes, ruptures/stock faible, valeur du stock, solde de chaque compte,
  alertes (ruptures, inventaires en cours) — §12.
- Blueprint `rapports` (§11) : rapports Ventes et Achats filtrables par date
  et regroupables (produit/catégorie/poste/projet/vendeur ou
  fournisseur/catégorie/poste/projet), rapport Stocks (état + mouvements de
  la période), rapport Comptes. Exports Excel (openpyxl) et PDF (ReportLab)
  pour Ventes et Achats — le gabarit est générique, **à ajuster une fois le
  modèle comptable réel d'Akiba fourni** (§11.3 demande un calque exact de
  l'existant, non disponible dans ce dépôt).
- Production (`app/models/production.py`, blueprint `production`) : déclaration
  de fabrication (produit, quantité, responsable, date, lot/DDM-DLC
  facultatifs), ajoute automatiquement le produit fabriqué au stock (mouvement
  tracé, motif "fabrication") et met à jour la traçabilité alimentaire
  courante de la fiche produit — §10. La gestion de recettes (déduction
  automatique des ingrédients) reste hors V1, comme prévu par la spec §10.4.
- RH (`app/models/rh.py`, blueprint `rh`) : fiche salarié (identité, contrat,
  poste/projet), suivi salaires mensuels/rémunérations journalières/avances/
  primes/retenues avec historique par salarié. Une rémunération versée avec
  moyen de paiement débite le compte financier correspondant ; une retenue
  (ou un montant non encore versé) n'a aucun effet sur les comptes tant
  qu'aucun moyen de paiement n'est renseigné — §5.4.
- Sécurité de session (§1.5/§3 CDC v1) : déconnexion automatique par
  inactivité (`INACTIVITY_TIMEOUT_MINUTES`, 5 min par défaut — timer JS
  réinitialisé à chaque interaction, `app/static/js/inactivity.js`) sur
  toutes les pages authentifiées, **et** après chaque vente au PDV un
  choix explicite est proposé au vendeur ("Vente suivante" / "Terminer ma
  session") plutôt qu'une déconnexion forcée systématique — pensé pour un
  poste avec file de clients, tout en gardant le filet de sécurité de
  l'inactivité en cas d'oubli ou d'abandon du poste.
- Sauvegardes (`app/admin/backup_service.py`, écran `admin/sauvegardes`) :
  sauvegarde manuelle horodatée (base chiffrée + pièces jointes) sous
  `instance/sauvegardes/`, purge automatique au-delà de
  `BACKUP_KEEP_COUNT` (10), restauration par écrasement direct avec
  confirmation. Journal d'audit **volontairement séparé de la base**
  (`instance/audit.log`, fichier plat) : le CDC exige que le log de
  restauration soit écrit avant l'écrasement de la base, donc un stockage
  dans la base elle-même serait perdu au moment précis où il doit faire
  foi. Testé de bout en bout (écriture → sauvegarde → nouvelle écriture →
  restauration → vérification du retour à l'état sauvegardé), pas
  seulement en surface — §13.1.
- Rapports : regroupement "Date (évolution)" ajouté sur Ventes et Achats
  (§9.4 CDC v1 — tendance dans le temps, réutilise le même moteur de
  rapport/export que les autres regroupements). Widget "Produits les plus
  vendus ce mois-ci" sur le tableau de bord.
- PDV : panneau "Dernières ventes de la session" accessible depuis l'en-tête
  (icône historique), pour éviter une double saisie après une hésitation ou
  un rafraîchissement de page — §1.6 CDC v1.
- Purge des sous-profils suspendus (§3.2) : commande
  `flask --app run.py purge-suspended-users`, supprime les sous-profils
  suspendus depuis plus de `SUBPROFILE_SUSPENSION_PURGE_DAYS` jours (90 par
  défaut). Les opérations déjà enregistrées par ces utilisateurs sont
  conservées (nom figé en texte sur chaque opération), seul l'enregistrement
  utilisateur disparaît — testé, y compris la préservation de l'historique.
  Volontairement une commande CLI plutôt qu'un scheduler en process : elle
  est prête à être appelée par le Planificateur de tâches Windows une fois
  le choix de déploiement tranché, sans présumer de ce choix.
- Clients (`app/models/client.py`, blueprint `clients`) : fiche (types
  enregistré/adhérent/grossiste/agence de voyage, coordonnées),
  historique des achats automatique (relation vers `Vente`), **vente à
  crédit** — au PDV, un client enregistré peut être sélectionné (recherche
  dans un panneau dédié) et le ticket réglé partiellement, le reste étant
  porté sur son solde dû ; une fiche client permet ensuite d'enregistrer
  les paiements de crédit, qui créditent le compte financier et réduisent
  le solde. Le "client de passage" reste un simple champ texte libre, sans
  fiche permanente, comme demandé (§3.2 CDC v1, §5.2 spec) — testé de bout
  en bout (vente à crédit → solde client → paiement partiel → solde mis à
  jour → compte financier crédité).
- Sécurité et ergonomie du code PIN (§3 spec + retour utilisateur) :
  - PIN systématiquement à **4 chiffres exactement**, plus de plage 4-8 —
    cohérent partout (connexion, création, réinitialisation).
  - Saisie clavier **et** tactile sur l'écran de connexion (`enter_pin.html`) :
    le champ réel reste focusable (pas `sr-only`), écoute le clavier comme
    le pavé à l'écran, filtre les caractères non numériques, limite à 4
    chiffres, et **soumet automatiquement** dès le 4e chiffre saisi.
  - Le code PIN n'est plus saisi par l'administrateur : il est **généré
    aléatoirement** (`secrets`, module cryptographique) à la création d'un
    utilisateur ou à la réinitialisation, affiché une seule fois sur une
    page dédiée pour être communiqué à l'utilisateur, jamais stocké en
    clair ni journalisé.
- RH : suivi des **absences** sur la fiche salarié (`app/models/rh.py::Absence`)
  — maladie/congé payé/congé sans solde/injustifiée/autre, période Du-Au (la
  date de fin recopie automatiquement la date de début tant qu'elle n'est
  pas modifiée, cas le plus fréquent d'une absence d'un jour), total de
  jours affiché sur la fiche.
- Achats **récurrents** (`AchatRecurrent`, écran `achats/recurrents`) :
  modèles réutilisables (bois, quincaillerie, bouffe, wifi...) mémorisant le
  classement habituel (poste/catégorie/fournisseur/montant). Des boutons de
  lancement rapide sur la page Achats préremplissent le formulaire depuis un
  modèle (`?modele=<id>`) — l'utilisateur vérifie et ajuste avant
  d'enregistrer, rien n'est jamais créé automatiquement sans confirmation.
- 95 tests pytest (auth, caisse, PDV, admin, achats, stocks, rapports,
  production, RH, sécurité de session, sauvegardes, purge utilisateurs,
  clients, permissions/menu, tarifs et rabais).
- Rabais automatique par tarif (`TypeTarif.pourcentage_rabais` /
  `rabais_actif`, Administration > Tarifs) : un pourcentage de rabais
  (ex. Adhérent -10%) peut être activé/désactivé par tarif, calculé à partir
  du **prix de référence** de chaque produit (nouveau champ sur la fiche
  produit, indépendant du prix d'achat), toujours **arrondi à la centaine
  supérieure** (`arrondir_centaine_superieure`, `app/models/catalogue.py`).
  Un prix saisi à la main sur la fiche produit pour un tarif donné prime
  toujours sur ce calcul automatique — le rabais ne s'applique que si aucun
  prix manuel n'existe pour ce couple produit/tarif. Le Point de Vente
  expose ces prix calculés au même titre que les prix manuels
  (`app/pos/routes.py::_prix_disponibles`), pas seulement en base au moment
  de l'encaissement.
- Refonte UX des formulaires (retour utilisateur : "pas intuitifs") :
  - Système de macros Jinja partagé (`app/templates/_form_macros.html`,
    `field()` / `actions()`) pour un rendu de champ cohérent partout : label
    avec astérisque rouge si obligatoire ou mention "(facultatif)" sinon,
    bordure rouge + message d'erreur sous le champ concerné, aide contextuelle
    optionnelle, boutons Annuler/Valider toujours pairés en pleine largeur.
    Appliqué à ~18 formulaires (achats, produits, postes/projets/catégories/
    sous-catégories, fournisseurs, utilisateurs, RH, clients, ajustement et
    inventaire de stock, production). Les cas volontairement laissés en
    dehors : boucle dynamique des tarifs par produit, champs montant en
    grande taille de la caisse, filtres de date des rapports (de simples
    filtres GET, pas de saisie de données).
  - Filtrage cascade catégorie → sous-catégorie en JS générique
    (`app/static/js/cascade.js` + `sous_categories_par_categorie()` dans
    `app/models/catalogue.py`) : le menu déroulant de sous-catégorie ne
    propose que celles de la catégorie choisie, réutilisé sur achats et
    fiche produit.
  - Bandeau explicatif ajouté sur le formulaire d'achat pour clarifier la
    différence achat de stock / dépense générale au moment de la saisie.
  - Passage en **grille 2 colonnes** (retour utilisateur : formulaires trop
    étroits pour la largeur d'écran disponible) sur les formulaires
    autonomes qui empilaient tous leurs champs en une seule colonne
    resserrée (utilisateur, salarié, client, production, mouvement de
    caisse, ajustement de stock) : champs courts côte à côte (nom/téléphone,
    poste/date...), champs longs (adresse, observations) qui restent en
    pleine largeur. Conteneur élargi en conséquence (`max-w-2xl`/`max-w-3xl`
    selon le nombre de champs). Les formulaires déjà en panneau latéral
    à côté d'une liste (postes, projets, fournisseurs...) gardent leur mise
    en page mais les champs courts y sont désormais aussi appariés.

- Déploiement final tranché par l'utilisateur (§2.1, §15.1 spec) : fenêtre
  native pywebview + PyInstaller, téléchargements autorisés comme dans un
  navigateur. `desktop.py` fait tourner l'app via Waitress (serveur WSGI de
  production, pas le serveur de dev Flask) dans un thread, sur un port local
  libre choisi dynamiquement, et ouvre une fenêtre pywebview dessus —
  `webview.settings["ALLOW_DOWNLOADS"] = True` active la boîte de dialogue
  Windows native "Enregistrer sous" à chaque téléchargement (exports
  Excel/PDF, factures...), vérifié dans le code source de pywebview
  (`platforms/edgechromium.py::on_download_starting`). `config.py` détecte
  l'exécution en `.exe` PyInstaller (`sys.frozen`) et redirige alors la base
  de données, les sauvegardes et les pièces jointes vers
  `%LOCALAPPDATA%\AKIBA APP\` (jamais dans le dossier d'installation, en
  lecture seule ou éphémère) ; `FLASK_SECRET_KEY`/`DB_ENCRYPTION_KEY` sont
  auto-générés (générateur cryptographique) et persistés au premier
  lancement si aucune variable d'environnement n'est fournie — aucun `.env`
  à éditer à la main pour l'utilisateur final. `app/bootstrap.py` amorce ce
  premier lancement : crée les 4 profils par défaut et un compte
  Administrateur avec un **PIN aléatoire** révélé une seule fois dans une
  boîte de dialogue Windows (jamais le PIN fixe "0000" du seed de dev), et
  ne crée **aucun catalogue de démonstration** (contrairement à
  `flask seed-db`, réservé au développement). Testé de bout en bout : build
  réel via `pyinstaller desktop.spec` (~35 Mo), exécutable lancé
  indépendamment de l'environnement de dev, fenêtre native "AKIBA APP"
  ouverte, page de connexion et CSS servis depuis l'intérieur du .exe,
  premier démarrage vérifié (base vierge → 4 profils + PIN admin généré →
  fichiers écrits dans `%LOCALAPPDATA%`).
- Ouverture réelle du tiroir-caisse (§6.5, §7.5) : `app/caisse/printer.py`
  envoie la commande ESC/POS "kick drawer" en job d'impression RAW direct au
  spouleur Windows (`pywin32`/`win32print`, sans passer par GDI) — nom de
  l'imprimante configurable en Administration (`ParametresImprimante`),
  bouton "Ouvrir le tiroir" indépendant de toute vente sur la page Caisse du
  PDV, et déclenchement automatique sur un mouvement de caisse dont le moyen
  de paiement a `ouvre_tiroir=True`. **Validé de bout en bout avec le vrai
  matériel (imprimante POS-80 USB) : le tiroir s'ouvre physiquement.**
  Piège rencontré et à surveiller en cas de réinstallation sur une nouvelle
  machine ou après un débranchement/rebranchement de l'imprimante : Windows
  peut créer un nouveau port USB virtuel (ex. `USB002`) distinct de celui
  auquel l'imprimante a été initialement associée (`USB001`), sans mettre à
  jour l'imprimante existante — la file d'attente reste alors bloquée en
  erreur dès le premier job (`Get-Printer` affiche `PrinterStatus=Error` et
  un `JobCount` qui grimpe), et **aucune commande n'atteint jamais
  l'imprimante silencieusement**. Diagnostic : `Get-Printer -Name "<nom>" |
  Select PrinterStatus,JobCount` ; correctif : identifier le bon port via
  `Get-PrinterPort` (celui dont la description nomme l'imprimante, pas le
  port générique "USB00x — Port d'imprimante virtuelle pour USB") puis
  `Set-Printer -Name "<nom>" -PortName "<bon port>"`, et vider la file
  bloquée (`Get-PrintJob -PrinterName "<nom>" | Remove-PrintJob`).
