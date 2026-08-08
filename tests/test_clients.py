def _creer_client(client, nom="Client Test"):
    client.post(
        "/clients/nouveau",
        data={"type_client": "adherent", "nom": nom, "telephone": "032 00 00 00"},
    )
    from app.models import Client as ClientModel

    return ClientModel.query.filter_by(nom=nom).first()


def test_creer_client(client, login_admin, catalogue):
    c = _creer_client(client)
    assert c is not None
    assert c.type_client == "adherent"
    assert c.solde_credit == 0


def test_vente_a_credit_augmente_le_solde_client(client, login_seller, catalogue, app, db):
    from app.models import Client as ClientModel

    with app.app_context():
        c = ClientModel(type_client="grossiste", nom="Grossiste Test")
        db.session.add(c)
        db.session.commit()
        client_id = c.id

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})

    payload = {
        "type_tarif_id": catalogue["type_tarif_id"],
        "client_id": client_id,
        "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 2, "remise": 0, "offert": False}],
        "paiements": [{"moyen_paiement_id": catalogue["moyen_paiement_id"], "montant": 6000}],
        "a_credit": True,
    }
    response = client.post("/pos/vente", json=payload)
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    from app.extensions import db
    from app.models import Client as ClientModel
    from app.models import CompteFinancier, Vente

    c_apres = db.session.get(ClientModel, client_id)
    assert c_apres.solde_credit == 10000  # total 16000 - payé 6000

    compte = db.session.get(CompteFinancier, catalogue["caisse_id"])
    assert compte.solde == 6000  # seule la part payée arrive en caisse

    vente = Vente.query.order_by(Vente.id.desc()).first()
    assert vente.montant_credit == 10000
    assert vente.client_id == client_id
    assert vente.client_nom == "Grossiste Test"


def test_vente_a_credit_sans_client_est_rejetee(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})

    payload = {
        "type_tarif_id": catalogue["type_tarif_id"],
        "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 1, "remise": 0, "offert": False}],
        "paiements": [],
        "a_credit": True,
    }
    response = client.post("/pos/vente", json=payload)
    assert response.status_code == 400
    assert "client enregistré" in response.get_json()["error"]


def test_paiement_credit_reduit_le_solde_et_credite_le_compte(client, login_admin, catalogue):
    c = _creer_client(client, "Grossiste Test")
    from app.extensions import db
    from app.models import Client as ClientModel

    c.solde_credit = 10000
    db.session.commit()

    response = client.post(
        f"/clients/{c.id}/paiement",
        data={
            "montant": "4000",
            "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
            "date_paiement": "2024-01-15",
        },
    )
    assert response.status_code == 302

    c_apres = db.session.get(ClientModel, c.id)
    assert c_apres.solde_credit == 6000

    from app.models import CompteFinancier

    compte = db.session.get(CompteFinancier, catalogue["caisse_id"])
    assert compte.solde == 4000


def test_paiement_credit_en_euros_credite_le_compte_dans_sa_devise(client, login_admin, catalogue, db):
    from app.extensions import db as _db
    from app.models import Client as ClientModel, CompteFinancier, MoyenPaiement, TauxChange

    compte_euro = CompteFinancier(name="Caisse Euro", devise="€")
    _db.session.add(compte_euro)
    _db.session.flush()
    moyen_euro = MoyenPaiement(name="Espèces Euro", compte_financier_id=compte_euro.id)
    _db.session.add(moyen_euro)
    TauxChange.get().ariary_pour_un_euro = 4000
    _db.session.commit()

    c = _creer_client(client, "Grossiste Euro")
    c.solde_credit = 8000  # 8000 Ar de dette
    _db.session.commit()

    # Rembourse 2 € (= 8000 Ar au taux 4000) : doit couvrir toute la dette et
    # créditer le compte Euro de 2 €, pas de "8000 €".
    response = client.post(
        f"/clients/{c.id}/paiement",
        data={"montant": "2", "moyen_paiement_id": str(moyen_euro.id), "date_paiement": "2024-01-15"},
    )
    assert response.status_code == 302

    c_apres = _db.session.get(ClientModel, c.id)
    assert c_apres.solde_credit == 0

    _db.session.refresh(compte_euro)
    assert compte_euro.solde == 2


def test_paiement_credit_superieur_au_solde_refuse(client, login_admin, catalogue):
    c = _creer_client(client, "Grossiste Test")
    from app.extensions import db
    from app.models import Client as ClientModel

    c.solde_credit = 1000
    db.session.commit()

    client.post(
        f"/clients/{c.id}/paiement",
        data={
            "montant": "5000",
            "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
            "date_paiement": "2024-01-15",
        },
    )

    c_apres = db.session.get(ClientModel, c.id)
    assert c_apres.solde_credit == 1000  # inchangé


def test_ticket_solde_narrete_plus_a_credit_sur_la_fiche(client, login_admin, catalogue, app, db):
    from app.models import Client as ClientModel

    with app.app_context():
        c = ClientModel(type_client="grossiste", nom="Grossiste Solde")
        db.session.add(c)
        db.session.commit()
        client_id = c.id

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    payload = {
        "type_tarif_id": catalogue["type_tarif_id"],
        "client_id": client_id,
        "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 2, "remise": 0, "offert": False}],
        "paiements": [{"moyen_paiement_id": catalogue["moyen_paiement_id"], "montant": 6000}],
        "a_credit": True,
    }
    client.post("/pos/vente", json=payload)

    from app.models import Vente

    vente = Vente.query.filter_by(client_id=client_id).first()
    assert vente.credit_solde_restant == 10000

    # Tant que le solde n'est pas réglé, "à crédit" doit apparaître sur la fiche.
    fiche_avant = client.get(f"/clients/{client_id}")
    assert f"Ticket #{vente.id}".encode() in fiche_avant.data
    assert "à crédit".encode() in fiche_avant.data

    # Paiement intégral du solde dû par ce client.
    client.post(
        f"/clients/{client_id}/paiement",
        data={
            "montant": "10000",
            "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
            "date_paiement": "2024-01-20",
        },
    )

    db.session.refresh(vente)
    assert vente.credit_solde_restant == 0
    assert vente.montant_credit == 10000  # historique inchangé

    fiche_apres = client.get(f"/clients/{client_id}")
    assert "à crédit".encode() not in fiche_apres.data


def test_clients_requires_permission(client, login_seller):
    response = client.get("/clients/")
    assert response.status_code == 403
