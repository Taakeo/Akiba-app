from datetime import date, datetime, timezone


def _creer_vente(db, catalogue, quantite=2, prix_unitaire=8000):
    from app.models import CaisseSession, LigneVente, Vente

    session = CaisseSession(
        compte_financier_id=catalogue["caisse_id"], fond_ouverture=0, ouverte_par_nom="Admin"
    )
    db.session.add(session)
    db.session.flush()

    vente = Vente(
        caisse_session_id=session.id,
        type_tarif_id=catalogue["type_tarif_id"],
        created_by_name="Admin",
        sous_total=quantite * prix_unitaire,
        total=quantite * prix_unitaire,
    )
    db.session.add(vente)
    db.session.flush()

    from app.models import Produit

    produit = db.session.get(Produit, catalogue["produit_id"])
    ligne = LigneVente(
        vente_id=vente.id,
        produit_id=produit.id,
        produit_nom=produit.name,
        poste_id=produit.poste_id,
        categorie_id=produit.categorie_id,
        quantite=quantite,
        prix_unitaire=prix_unitaire,
        total_ligne=quantite * prix_unitaire,
    )
    db.session.add(ligne)
    db.session.commit()
    return vente


def test_rapport_ventes_regroupe_par_produit(client, login_admin, catalogue, app, db):
    with app.app_context():
        _creer_vente(db, catalogue, quantite=3, prix_unitaire=8000)

    today = date.today().isoformat()
    response = client.get(f"/rapports/ventes?debut={today}&fin={today}&group_by=produit")
    assert response.status_code == 200
    assert b"Tablette Chocolat 70%" in response.data
    assert "24 000".encode() in response.data or b"24000" in response.data


def test_rapport_ventes_export_xlsx(client, login_admin, catalogue, app, db):
    with app.app_context():
        _creer_vente(db, catalogue, quantite=1, prix_unitaire=8000)

    today = date.today().isoformat()
    response = client.get(f"/rapports/ventes/export.xlsx?debut={today}&fin={today}")
    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert len(response.data) > 0


def test_rapport_ventes_export_pdf(client, login_admin, catalogue, app, db):
    with app.app_context():
        _creer_vente(db, catalogue, quantite=1, prix_unitaire=8000)

    today = date.today().isoformat()
    response = client.get(f"/rapports/ventes/export.pdf?debut={today}&fin={today}")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data[:4] == b"%PDF"


def test_rapports_requires_permission(client, login_seller):
    response = client.get("/rapports/")
    assert response.status_code == 403


def test_dashboard_shows_ca_jour(client, login_admin, catalogue, app, db):
    with app.app_context():
        _creer_vente(db, catalogue, quantite=2, prix_unitaire=8000)

    response = client.get("/")
    assert response.status_code == 200
    assert "16 000".encode() in response.data


def test_rapport_production_regroupe_par_produit(client, login_admin, catalogue, app, db):
    from datetime import date as date_cls

    with app.app_context():
        from app.models import Fabrication, Produit

        produit = db.session.get(Produit, catalogue["produit_id"])
        db.session.add(
            Fabrication(
                produit_id=produit.id,
                quantite=25,
                responsable_nom="Lala",
                date_fabrication=date_cls.today(),
                created_by_name="Admin",
            )
        )
        db.session.commit()

    today = date.today().isoformat()
    response = client.get(f"/rapports/production?debut={today}&fin={today}")
    assert response.status_code == 200
    assert b"Tablette Chocolat 70%" in response.data
    assert b"25" in response.data


def test_rapport_rh_soustrait_les_retenues(client, login_admin, catalogue, app, db):
    from datetime import date as date_cls

    with app.app_context():
        from app.models import RemunerationSalarie, Salarie

        salarie = Salarie(nom="Lala Rakoto", poste_id=catalogue["poste_id"])
        db.session.add(salarie)
        db.session.flush()
        db.session.add_all(
            [
                RemunerationSalarie(
                    salarie_id=salarie.id,
                    type_remuneration="salaire_mensuel",
                    montant=300000,
                    date_versement=date_cls.today(),
                    created_by_name="Admin",
                ),
                RemunerationSalarie(
                    salarie_id=salarie.id,
                    type_remuneration="retenue",
                    montant=5000,
                    date_versement=date_cls.today(),
                    created_by_name="Admin",
                ),
            ]
        )
        db.session.commit()

    today = date.today().isoformat()
    response = client.get(f"/rapports/rh?debut={today}&fin={today}&group_by=salarie")
    assert response.status_code == 200
    assert b"Lala Rakoto" in response.data
    assert "295 000".encode() in response.data  # 300000 - 5000


def test_rapports_production_rh_requires_permission(client, login_seller):
    assert client.get("/rapports/production").status_code == 403
    assert client.get("/rapports/rh").status_code == 403


def test_rapport_ventes_groupe_par_date_ordre_chronologique(client, login_admin, catalogue, app, db):
    with app.app_context():
        _creer_vente(db, catalogue, quantite=1, prix_unitaire=8000)

    today = date.today().isoformat()
    response = client.get(f"/rapports/ventes?debut={today}&fin={today}&group_by=date")
    assert response.status_code == 200
    assert today.encode() in response.data


def test_dashboard_affiche_top_produits(client, login_admin, catalogue, app, db):
    with app.app_context():
        _creer_vente(db, catalogue, quantite=4, prix_unitaire=8000)

    response = client.get("/")
    assert response.status_code == 200
    assert b"Produits les plus vendus" in response.data
    assert b"Tablette Chocolat 70%" in response.data
    assert b"4 vendu" in response.data
