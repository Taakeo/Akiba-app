from sqlalchemy import inspect, text


def _colonnes(db, table):
    return {c["name"] for c in inspect(db.engine).get_columns(table)}


def test_appliquer_migrations_ajoute_les_colonnes_manquantes_sans_perte_de_donnees(app, db, catalogue):
    # create_app() (fixture `app`) a déjà tourné avec le schéma actuel — pour
    # simuler une vraie base "avant mise à jour" (comme celle déjà en
    # production chez Akiba), on retire ici les colonnes que la migration est
    # censée ajouter, puis on rappelle la fonction et on vérifie qu'elle les
    # restaure sans toucher aux données existantes.
    from app.db_migrations import appliquer_migrations
    from app.models import Produit

    with app.app_context():
        # Seules les colonnes sans contrainte de clé étrangère sont testées en
        # DROP/re-ADD ici : SQLite refuse de son côté un DROP COLUMN sur une
        # colonne de clé étrangère auto-référencée (limitation de simulation,
        # sans rapport avec la migration elle-même — celle-ci n'ajoute que des
        # colonnes simples, sans contrainte FK réellement appliquée en SQLite).
        db.session.execute(text("ALTER TABLE produit DROP COLUMN vendable_pdv"))
        db.session.execute(text("ALTER TABLE fabrication DROP COLUMN quantite_packaging"))
        db.session.commit()

        assert "vendable_pdv" not in _colonnes(db, "produit")
        assert "quantite_packaging" not in _colonnes(db, "fabrication")

        appliquer_migrations()

        assert "vendable_pdv" in _colonnes(db, "produit")
        assert "quantite_packaging" in _colonnes(db, "fabrication")
        # Toujours présentes (jamais retirées ici) : confirme que la fonction
        # ne touche pas à une colonne déjà à jour.
        assert "packaging_produit_id" in _colonnes(db, "produit")
        assert "packaging_produit_id" in _colonnes(db, "fabrication")

        # Aucune perte de données existantes, et une valeur par défaut
        # correcte appliquée à la colonne recréée (vrai par défaut).
        produit = db.session.get(Produit, catalogue["produit_id"])
        assert produit.name == "Tablette Chocolat 70%"
        assert produit.vendable_pdv is True


def test_appliquer_migrations_backfill_le_droit_ventes_externes_une_seule_fois(app, db):
    from app.db_migrations import appliquer_migrations
    from app.models import Profile

    with app.app_context():
        profile = Profile(code="responsable", name="Responsable", icon="manage_accounts")
        profile.permissions = ["point_de_vente", "achats"]  # ancienne base, sans le nouveau droit
        db.session.add(profile)
        db.session.commit()

        db.session.execute(text("ALTER TABLE produit DROP COLUMN vendable_pdv"))
        db.session.commit()

        appliquer_migrations()
        db.session.refresh(profile)
        assert "ventes_externes" in profile.permissions

        # Un administrateur retire volontairement le droit ensuite : un
        # redémarrage normal (aucune colonne manquante cette fois) ne doit
        # jamais le réimposer.
        profile.permissions = [p for p in profile.permissions if p != "ventes_externes"]
        db.session.commit()

        appliquer_migrations()
        db.session.refresh(profile)
        assert "ventes_externes" not in profile.permissions
