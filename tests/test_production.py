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
