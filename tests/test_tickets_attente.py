def _ouvrir_session(client):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})


def test_liste_tickets_sans_session_ouverte_echoue(client, login_seller, catalogue):
    response = client.get("/pos/tickets")
    assert response.status_code == 400


def test_liste_tickets_vide_au_depart(client, login_seller, catalogue):
    _ouvrir_session(client)
    response = client.get("/pos/tickets")
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["tickets"] == []


def test_creer_puis_lister_un_ticket(client, login_seller, catalogue):
    _ouvrir_session(client)
    response = client.post(
        "/pos/tickets",
        json={
            "nom": "Table 3",
            "type_tarif_id": catalogue["type_tarif_id"],
            "client_id": None,
            "client_nom": None,
            "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 2, "remise": 0, "offert": False}],
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    ticket_id = body["ticket"]["id"]
    assert body["ticket"]["nom"] == "Table 3"
    assert body["ticket"]["lignes"] == [
        {"produit_id": catalogue["produit_id"], "quantite": 2, "remise": 0, "offert": False}
    ]

    liste = client.get("/pos/tickets").get_json()
    assert len(liste["tickets"]) == 1
    assert liste["tickets"][0]["id"] == ticket_id


def test_mettre_a_jour_un_ticket(client, login_seller, catalogue):
    _ouvrir_session(client)
    creation = client.post(
        "/pos/tickets",
        json={"nom": "Ticket 1", "type_tarif_id": catalogue["type_tarif_id"], "lignes": []},
    ).get_json()
    ticket_id = creation["ticket"]["id"]

    reponse = client.post(
        f"/pos/tickets/{ticket_id}",
        json={
            "nom": "Table 5 renommée",
            "type_tarif_id": catalogue["type_tarif_id"],
            "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 1, "remise": 0, "offert": False}],
        },
    )
    assert reponse.status_code == 200
    body = reponse.get_json()
    assert body["ticket"]["nom"] == "Table 5 renommée"
    assert len(body["ticket"]["lignes"]) == 1


def test_supprimer_un_ticket(client, login_seller, catalogue):
    _ouvrir_session(client)
    creation = client.post("/pos/tickets", json={"nom": "Ticket X", "lignes": []}).get_json()
    ticket_id = creation["ticket"]["id"]

    reponse = client.post(f"/pos/tickets/{ticket_id}/supprimer")
    assert reponse.status_code == 200
    assert reponse.get_json()["ok"] is True

    liste = client.get("/pos/tickets").get_json()
    assert liste["tickets"] == []


def test_ticket_dune_autre_session_est_inaccessible(client, login_seller, catalogue, app, db):
    from app.caisse.services import get_open_session
    from app.models import TicketAttente

    _ouvrir_session(client)
    with app.app_context():
        session = get_open_session()
        ticket = TicketAttente(
            caisse_session_id=session.id + 999,  # session inexistante/autre
            nom="Autre session",
            created_by_name="Sarah",
        )
        db.session.add(ticket)
        db.session.commit()
        ticket_id = ticket.id

    reponse = client.post(f"/pos/tickets/{ticket_id}", json={"nom": "Piraté", "lignes": []})
    assert reponse.status_code == 404


def test_ticket_survit_a_une_nouvelle_requete_get(client, login_seller, catalogue):
    """Persistance : les tickets créés restent visibles après un GET
    ultérieur, sans dépendre d'un état en mémoire du serveur applicatif."""
    _ouvrir_session(client)
    client.post("/pos/tickets", json={"nom": "Table A", "lignes": []})
    client.post("/pos/tickets", json={"nom": "Table B", "lignes": []})

    liste = client.get("/pos/tickets").get_json()
    noms = {t["nom"] for t in liste["tickets"]}
    assert noms == {"Table A", "Table B"}


def test_checkout_avec_ticket_attente_le_supprime_apres_encaissement(client, login_seller, catalogue):
    _ouvrir_session(client)
    creation = client.post(
        "/pos/tickets",
        json={
            "nom": "Table 3",
            "type_tarif_id": catalogue["type_tarif_id"],
            "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 1, "remise": 0, "offert": False}],
        },
    ).get_json()
    ticket_id = creation["ticket"]["id"]

    payload = {
        "type_tarif_id": catalogue["type_tarif_id"],
        "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 1, "remise": 0, "offert": False}],
        "paiements": [{"moyen_paiement_id": catalogue["moyen_paiement_id"], "montant": 8000}],
        "ticket_attente_id": ticket_id,
    }
    response = client.post("/pos/vente", json=payload)
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    liste = client.get("/pos/tickets").get_json()
    assert liste["tickets"] == []
