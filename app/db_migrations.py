"""Migrations légères de schéma, appelées après db.create_all() (app/__init__.py).

Ce projet n'utilise pas Alembic/Flask-Migrate : db.create_all() crée les tables
manquantes mais n'ajoute jamais de colonne à une table déjà existante. Pour ne
pas casser la base réelle d'une association déjà en production quand une
nouvelle version de l'app ajoute une colonne à un modèle existant (ex. un
utilisateur qui remplace juste le .exe sans repartir d'une base vierge), ce
module vérifie chaque colonne attendue et l'ajoute lui-même via ALTER TABLE si
elle manque. Idempotent : ne fait rien sur une base déjà à jour, y compris
toute base de test (toujours créée fraîche, donc déjà à jour dès sa création)."""

from sqlalchemy import inspect, text

from .extensions import db

# (table, colonne, définition SQL complète après le nom de colonne)
COLONNES_ATTENDUES = [
    ("produit", "vendable_pdv", "BOOLEAN NOT NULL DEFAULT 1"),
    ("produit", "packaging_produit_id", "INTEGER"),
    ("fabrication", "packaging_produit_id", "INTEGER"),
    ("fabrication", "quantite_packaging", "INTEGER"),
    # Annulation (droit "corrections") étendue aux achats, fabrications,
    # ventes externes et rémunérations — même principe que Vente.statut,
    # jamais de suppression (app/models/achat.py, production.py,
    # vente_externe.py, rh.py).
    ("achat", "is_annule", "BOOLEAN NOT NULL DEFAULT 0"),
    ("achat", "annule_motif", "TEXT"),
    ("achat", "annule_par_nom", "VARCHAR(120)"),
    ("achat", "annule_le", "DATETIME"),
    ("fabrication", "is_annule", "BOOLEAN NOT NULL DEFAULT 0"),
    ("fabrication", "annule_motif", "TEXT"),
    ("fabrication", "annule_par_nom", "VARCHAR(120)"),
    ("fabrication", "annule_le", "DATETIME"),
    ("vente_externe", "is_annule", "BOOLEAN NOT NULL DEFAULT 0"),
    ("vente_externe", "annule_motif", "TEXT"),
    ("vente_externe", "annule_par_nom", "VARCHAR(120)"),
    ("vente_externe", "annule_le", "DATETIME"),
    ("remuneration_salarie", "is_annule", "BOOLEAN NOT NULL DEFAULT 0"),
    ("remuneration_salarie", "annule_motif", "TEXT"),
    ("remuneration_salarie", "annule_par_nom", "VARCHAR(120)"),
    ("remuneration_salarie", "annule_le", "DATETIME"),
    # Facture officielle étendue aux ventes externes (§ amélioration
    # facturation ventes externes) — même principe que vente.facture_id.
    ("vente_externe", "facture_id", "INTEGER"),
    # Correction de vente étendue (produits/quantités/paiement/client) — voir
    # app/models/ventes.py::Vente.derniere_correction_*.
    ("vente", "derniere_correction_motif", "TEXT"),
    ("vente", "derniere_correction_par_nom", "VARCHAR(120)"),
    ("vente", "derniere_correction_le", "DATETIME"),
    # Annulation d'une vente : jusqu'ici tracée uniquement en texte libre dans
    # vente.commentaire (préfixe "[ANNULÉE]") — mêmes champs structurés que
    # achat/fabrication/vente_externe/remuneration_salarie, nécessaires pour
    # lister précisément les corrections d'une session dans son rapport.
    ("vente", "annule_motif", "TEXT"),
    ("vente", "annule_par_nom", "VARCHAR(120)"),
    ("vente", "annule_le", "DATETIME"),
    # Un versement RH (salaire, avance, prime, retenue) payé en espèces PDV
    # n'était jamais rattaché à la session de caisse — jamais déduit du
    # théorique du tiroir ni visible dans son résumé/rapport, contrairement à
    # un achat (retour utilisateur). Voir app/models/rh.py::RemunerationSalarie.
    ("remuneration_salarie", "caisse_session_id", "INTEGER"),
]


def appliquer_migrations():
    """À appeler depuis create_app(), dans le même contexte applicatif que
    db.create_all() et juste après lui."""
    inspecteur = inspect(db.engine)
    noms_tables = set(inspecteur.get_table_names())

    colonnes_ajoutees = False
    for table, colonne, definition in COLONNES_ATTENDUES:
        if table not in noms_tables:
            # La table elle-même vient d'être créée par db.create_all(), déjà
            # avec cette colonne dans sa forme finale — rien à ajouter ici.
            continue
        colonnes_existantes = {c["name"] for c in inspecteur.get_columns(table)}
        if colonne in colonnes_existantes:
            continue
        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {colonne} {definition}"))
        colonnes_ajoutees = True

    db.session.commit()

    # Backfill du droit "ventes_externes" sur le profil Responsable déjà semé,
    # seulement au moment précis où une vraie mise à jour de schéma vient
    # d'avoir lieu (jamais à chaque démarrage ensuite) — pour ne jamais
    # réimposer ce droit si un administrateur le retire volontairement plus
    # tard. Sur une base vierge, DEFAULT_PROFILES (app/bootstrap.py) l'inclut
    # déjà directement : ce backfill ne sert qu'aux bases déjà en production.
    if colonnes_ajoutees:
        _backfill_droit_ventes_externes()

    # Backfills indépendants de tout changement de colonne (aucune colonne
    # n'est ajoutée pour ces droits) : exécutés à chaque démarrage, mais
    # rendus réellement ponctuels par MigrationFlag — une fois appliqué, plus
    # jamais réimposé, même si l'administrateur retire le droit ensuite.
    _backfill_permission_une_fois("responsable", "produits", "responsable_produits_v1")
    _backfill_permission_une_fois("responsable", "corrections", "responsable_corrections_v1")
    # Le vendeur a désormais aussi accès aux achats, stocks, clients et
    # production (retour utilisateur) — backfillé une seule fois sur les
    # bases déjà en production, jamais réimposé si retiré ensuite.
    _backfill_permission_une_fois("vendeur", "achats", "vendeur_achats_v1")
    _backfill_permission_une_fois("vendeur", "stocks", "vendeur_stocks_v1")
    _backfill_permission_une_fois("vendeur", "clients", "vendeur_clients_v1")
    _backfill_permission_une_fois("vendeur", "production", "vendeur_production_v1")


def _backfill_droit_ventes_externes():
    from .models import Profile

    responsable = Profile.query.filter_by(code="responsable").first()
    if responsable is None:
        return
    permissions = responsable.permissions
    if "ventes_externes" in permissions or "*" in permissions:
        return
    permissions.append("ventes_externes")
    responsable.permissions = permissions
    db.session.commit()


def _backfill_permission_une_fois(profile_code, permission, flag_key):
    """Ajoute `permission` au profil `profile_code` une seule fois, jamais
    plus après — que le profil l'ait ensuite ou non selon les choix de
    l'administrateur. Sur une base vierge, DEFAULT_PROFILES (app/bootstrap.py)
    inclut déjà directement ce droit : ce backfill ne sert qu'aux bases déjà
    en production, mises à jour depuis une version antérieure."""
    from .models import MigrationFlag, Profile

    if db.session.get(MigrationFlag, flag_key) is not None:
        return

    profile = Profile.query.filter_by(code=profile_code).first()
    if profile is not None:
        permissions = profile.permissions
        if permission not in permissions and "*" not in permissions:
            permissions.append(permission)
            profile.permissions = permissions

    db.session.add(MigrationFlag(key=flag_key))
    db.session.commit()
