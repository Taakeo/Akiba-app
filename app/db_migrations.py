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
