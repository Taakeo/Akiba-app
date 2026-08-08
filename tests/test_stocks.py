def test_stocks_requires_permission(client, login_seller):
    assert client.get("/stocks/").status_code == 403
    assert client.get("/stocks/ajustement").status_code == 403
    assert client.get("/stocks/inventaires").status_code == 403


def test_stocks_index_lists_produit(client, login_admin, catalogue):
    response = client.get("/stocks/")
    assert response.status_code == 200
    assert b"Tablette Chocolat 70%" in response.data


def test_ajustement_sortie_perte_decrements_stock(client, login_admin, catalogue):
    response = client.post(
        "/stocks/ajustement",
        data={
            "produit_id": str(catalogue["produit_id"]),
            "type_mouvement": "sortie",
            "motif_sortie": "perte",
            "motif_entree": "don",
            "quantite": "3",
            "commentaire": "Casse",
        },
    )
    assert response.status_code == 302

    from app.extensions import db
    from app.models import MouvementStock, Produit

    produit = db.session.get(Produit, catalogue["produit_id"])
    assert produit.stock_quantite == 7  # 10 - 3

    mouvement = MouvementStock.query.filter_by(produit_id=produit.id).first()
    assert mouvement.motif == "perte"
    assert mouvement.type_mouvement == "sortie"


def test_ajustement_sortie_insuffisante_bloquee(client, login_admin, catalogue):
    response = client.post(
        "/stocks/ajustement",
        data={
            "produit_id": str(catalogue["produit_id"]),
            "type_mouvement": "sortie",
            "motif_sortie": "perte",
            "motif_entree": "don",
            "quantite": "99",
        },
    )
    assert response.status_code == 200

    from app.extensions import db
    from app.models import Produit

    produit = db.session.get(Produit, catalogue["produit_id"])
    assert produit.stock_quantite == 10  # inchangé


def test_inventaire_general_cloture_applique_ecart(client, login_admin, catalogue):
    response = client.post("/stocks/inventaires/nouveau", data={"type_inventaire": "general"})
    assert response.status_code == 302
    inventaire_url = response.headers["Location"]

    from app.models import Inventaire, InventaireLigne

    inventaire = Inventaire.query.order_by(Inventaire.id.desc()).first()
    ligne = InventaireLigne.query.filter_by(inventaire_id=inventaire.id, produit_id=catalogue["produit_id"]).first()
    assert ligne.stock_theorique == 10

    response = client.post(inventaire_url, data={f"reel_{ligne.id}": "8"})
    assert response.status_code == 302

    from app.extensions import db
    from app.models import MouvementStock, Produit

    produit = db.session.get(Produit, catalogue["produit_id"])
    assert produit.stock_quantite == 8

    mouvement = MouvementStock.query.filter_by(produit_id=produit.id, motif="correction").first()
    assert mouvement is not None
    assert mouvement.type_mouvement == "sortie"
    assert mouvement.quantite == 2

    db.session.refresh(inventaire)
    assert inventaire.statut == "cloture"
