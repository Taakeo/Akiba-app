def test_fabrication_augmente_stock_et_trace_le_lot(client, login_admin, catalogue):
    response = client.post(
        "/production/nouvelle",
        data={
            "produit_id": str(catalogue["produit_id"]),
            "quantite": "12",
            "date_fabrication": "2024-02-01",
            "numero_lot": "LOT-2024-02",
            "ddm_dlc": "2025-02-01",
            "observations": "Cuvée test",
        },
    )
    assert response.status_code == 302

    from app.extensions import db
    from app.models import Fabrication, MouvementStock, Produit

    produit = db.session.get(Produit, catalogue["produit_id"])
    assert produit.stock_quantite == 22  # 10 initial + 12 fabriqués
    assert produit.numero_lot == "LOT-2024-02"
    assert produit.ddm_dlc.isoformat() == "2025-02-01"

    fabrication = Fabrication.query.filter_by(produit_id=produit.id).first()
    assert fabrication is not None
    # Le responsable n'est plus saisi à la main : c'est toujours l'utilisateur
    # connecté (traçabilité, cf. login_admin -> sous-profil "Admin").
    assert fabrication.responsable_nom == "Admin"
    assert fabrication.observations == "Cuvée test"

    mouvement = MouvementStock.query.filter_by(produit_id=produit.id, motif="fabrication").first()
    assert mouvement is not None
    assert mouvement.quantite == 12
    assert mouvement.type_mouvement == "entree"


def test_production_requires_permission(client, login_seller):
    response = client.get("/production/")
    assert response.status_code == 403


def test_modifier_fabrication_ne_touche_pas_au_stock(client, login_admin, catalogue, db):
    from app.models import Fabrication, Produit

    client.post(
        "/production/nouvelle",
        data={
            "produit_id": str(catalogue["produit_id"]),
            "quantite": "5",
            "date_fabrication": "2024-02-01",
            "observations": "Premier jet",
        },
    )
    fabrication = Fabrication.query.first()
    produit = db.session.get(Produit, catalogue["produit_id"])
    stock_apres_fabrication = produit.stock_quantite

    response = client.post(
        f"/production/{fabrication.id}/modifier",
        data={
            "date_fabrication": "2024-02-02",
            "numero_lot": "LOT-CORRIGE",
            "observations": "Note corrigée",
        },
    )
    assert response.status_code == 302

    db.session.refresh(fabrication)
    db.session.refresh(produit)
    assert fabrication.observations == "Note corrigée"
    assert fabrication.numero_lot == "LOT-CORRIGE"
    assert fabrication.date_fabrication.isoformat() == "2024-02-02"
    assert produit.stock_quantite == stock_apres_fabrication  # inchangé
    assert fabrication.responsable_nom == "Admin"  # inchangé, pas réassignable


def _creer_emballage(db, catalogue, name="Sachet tablette 20g", stock_quantite=10, seuil_alerte=5):
    from app.models import Produit

    emballage = Produit(
        name=name,
        categorie_id=catalogue["categorie_id"],
        poste_id=catalogue["poste_id"],
        vendable_pdv=False,
        stock_quantite=stock_quantite,
        seuil_alerte=seuil_alerte,
    )
    db.session.add(emballage)
    db.session.commit()
    return emballage.id


def test_fabrication_deduit_le_stock_emballage(client, login_admin, catalogue, db):
    emballage_id = _creer_emballage(db, catalogue)

    response = client.post(
        "/production/nouvelle",
        data={
            "produit_id": str(catalogue["produit_id"]),
            "quantite": "4",
            "date_fabrication": "2024-02-01",
            "packaging_produit_id": str(emballage_id),
            "quantite_packaging": "4",
        },
    )
    assert response.status_code == 302

    from app.models import Fabrication, MouvementStock, Produit

    emballage = db.session.get(Produit, emballage_id)
    assert emballage.stock_quantite == 6  # 10 initial - 4 consommés

    mouvement = MouvementStock.query.filter_by(produit_id=emballage_id, motif="fabrication").first()
    assert mouvement is not None
    assert mouvement.type_mouvement == "sortie"
    assert mouvement.quantite == 4

    fabrication = Fabrication.query.first()
    assert fabrication.packaging_produit_id == emballage_id
    assert fabrication.quantite_packaging == 4

    produit = db.session.get(Produit, catalogue["produit_id"])
    assert produit.stock_quantite == 14  # 10 initial + 4 fabriqués, inchangé par l'emballage


def test_fabrication_sans_quantite_packaging_reprend_la_quantite_fabriquee(client, login_admin, catalogue, db):
    emballage_id = _creer_emballage(db, catalogue, stock_quantite=20)

    client.post(
        "/production/nouvelle",
        data={
            "produit_id": str(catalogue["produit_id"]),
            "quantite": "6",
            "date_fabrication": "2024-02-01",
            "packaging_produit_id": str(emballage_id),
        },
    )

    from app.models import Produit

    emballage = db.session.get(Produit, emballage_id)
    assert emballage.stock_quantite == 14  # 20 - 6 (ratio 1:1 par défaut)


def test_fabrication_alerte_immediatement_si_emballage_faible(client, login_admin, catalogue, db):
    # Seuil d'alerte à 5, stock initial 6 -> après consommation de 4, il reste
    # 2 : sous le seuil, alerte attendue tout de suite (pas seulement sur le
    # tableau de bord), l'emballage n'étant jamais vendable au PDV.
    emballage_id = _creer_emballage(db, catalogue, stock_quantite=6, seuil_alerte=5)

    response = client.post(
        "/production/nouvelle",
        data={
            "produit_id": str(catalogue["produit_id"]),
            "quantite": "4",
            "date_fabrication": "2024-02-01",
            "packaging_produit_id": str(emballage_id),
            "quantite_packaging": "4",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"faible" in response.data.lower()


# --- Correction administrateur : annulation d'une fabrication ----------------


def test_annuler_fabrication_requiert_le_droit_corrections(client, login_seller, catalogue, db):
    from datetime import date

    from app.models import Fabrication

    fabrication = Fabrication(
        produit_id=catalogue["produit_id"], quantite=5, responsable_nom="Admin",
        date_fabrication=date(2024, 2, 1), created_by_name="Admin",
    )
    db.session.add(fabrication)
    db.session.commit()

    response = client.post(f"/production/{fabrication.id}/annuler", data={"motif": "Erreur"})
    assert response.status_code == 403


def test_annuler_fabrication_restaure_le_stock_et_lemballage(client, login_admin, catalogue, db):
    emballage_id = _creer_emballage(db, catalogue, stock_quantite=10)

    client.post(
        "/production/nouvelle",
        data={
            "produit_id": str(catalogue["produit_id"]),
            "quantite": "4",
            "date_fabrication": "2024-02-01",
            "packaging_produit_id": str(emballage_id),
            "quantite_packaging": "4",
        },
    )

    from app.models import Fabrication, Produit

    fabrication = Fabrication.query.first()
    produit = db.session.get(Produit, catalogue["produit_id"])
    emballage = db.session.get(Produit, emballage_id)
    assert produit.stock_quantite == 14  # 10 + 4
    assert emballage.stock_quantite == 6  # 10 - 4

    response = client.post(f"/production/{fabrication.id}/annuler", data={"motif": "Doublon"})
    assert response.status_code == 302

    db.session.refresh(produit)
    db.session.refresh(emballage)
    db.session.refresh(fabrication)
    assert produit.stock_quantite == 10  # rétabli
    assert emballage.stock_quantite == 10  # rétabli
    assert fabrication.is_annule is True


def test_annuler_fabrication_deja_annulee_est_refuse(client, login_admin, catalogue, db):
    client.post(
        "/production/nouvelle",
        data={"produit_id": str(catalogue["produit_id"]), "quantite": "4", "date_fabrication": "2024-02-01"},
    )
    from app.models import Fabrication, Produit

    fabrication = Fabrication.query.first()
    client.post(f"/production/{fabrication.id}/annuler", data={"motif": "Doublon"})
    produit = db.session.get(Produit, catalogue["produit_id"])
    stock_apres_premiere_annulation = produit.stock_quantite

    client.post(f"/production/{fabrication.id}/annuler", data={"motif": "Encore"})
    db.session.refresh(produit)
    assert produit.stock_quantite == stock_apres_premiere_annulation
