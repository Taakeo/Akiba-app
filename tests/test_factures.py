def _creer_client(db, app, nom="Client Test", adresse="Lot 12 Analakely, Antananarivo"):
    from app.models import Client

    with app.app_context():
        c = Client(type_client="enregistre", nom=nom, adresse=adresse)
        db.session.add(c)
        db.session.commit()
        return c.id


def _vente(client, catalogue, client_id=None, quantite=1, a_credit=False):
    total = 8000 * quantite
    payload = {
        "type_tarif_id": catalogue["type_tarif_id"],
        "client_id": client_id,
        "lignes": [{"produit_id": catalogue["produit_id"], "quantite": quantite, "remise": 0, "offert": False}],
        "paiements": [] if a_credit else [{"moyen_paiement_id": catalogue["moyen_paiement_id"], "montant": total}],
        "a_credit": a_credit,
    }
    response = client.post("/pos/vente", json=payload)
    assert response.status_code == 200
    return response.get_json()["redirect"].split("/")[-1].split("?")[0]


def test_generer_facture_service_cree_une_facture_numerotee(app, db, catalogue):
    from app.models import Client, MoyenPaiement, TypeTarif, Vente
    from app.caisse.services import crediter_compte
    from app.factures.services import generer_facture

    class FakeUser:
        id = None
        full_name = "Testeur"

    with app.app_context():
        client_obj = Client(nom="Client Test", adresse="Lot 12 Analakely")
        db.session.add(client_obj)
        db.session.flush()

        vente = Vente(
            caisse_session_id=1,  # non contrôlé par le service, juste requis en base
            type_tarif_id=catalogue["type_tarif_id"],
            client_id=client_obj.id,
            sous_total=8000,
            total=8000,
            created_by_name="Sarah",
        )
        db.session.add(vente)
        db.session.commit()

        facture = generer_facture(client_obj, [vente], FakeUser())

        assert facture.numero == "FA-000001"
        assert facture.total == 8000
        assert facture.client_adresse == "Lot 12 Analakely"
        assert vente.facture_id == facture.id


def test_generer_facture_refuse_client_sans_adresse(app, db, catalogue):
    from app.models import Client, Vente
    from app.factures.services import FactureError, generer_facture

    class FakeUser:
        id = None
        full_name = "Testeur"

    with app.app_context():
        client_obj = Client(nom="Sans Adresse")
        db.session.add(client_obj)
        db.session.flush()
        vente = Vente(
            caisse_session_id=1,
            type_tarif_id=catalogue["type_tarif_id"],
            client_id=client_obj.id,
            sous_total=8000,
            total=8000,
            created_by_name="Sarah",
        )
        db.session.add(vente)
        db.session.commit()

        try:
            generer_facture(client_obj, [vente], FakeUser())
            assert False, "devait lever FactureError"
        except FactureError as exc:
            assert "adresse" in str(exc).lower()


def test_generer_facture_refuse_ticket_deja_facture(app, db, catalogue):
    from app.models import Client, Vente
    from app.factures.services import FactureError, generer_facture

    class FakeUser:
        id = None
        full_name = "Testeur"

    with app.app_context():
        client_obj = Client(nom="Client Test", adresse="Lot 12")
        db.session.add(client_obj)
        db.session.flush()
        vente = Vente(
            caisse_session_id=1,
            type_tarif_id=catalogue["type_tarif_id"],
            client_id=client_obj.id,
            sous_total=8000,
            total=8000,
            created_by_name="Sarah",
        )
        db.session.add(vente)
        db.session.commit()

        generer_facture(client_obj, [vente], FakeUser())

        try:
            generer_facture(client_obj, [vente], FakeUser())
            assert False, "devait lever FactureError sur double facturation"
        except FactureError as exc:
            assert "déjà incluse" in str(exc).lower() or "déjà" in str(exc).lower()


def test_route_depuis_vente_cree_la_facture(client, login_seller, catalogue, app, db):
    client_id = _creer_client(db, app)
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    vente_id = _vente(client, catalogue, client_id=client_id, quantite=2)

    response = client.post(f"/factures/depuis-vente/{vente_id}", follow_redirects=True)
    assert response.status_code == 200
    assert b"FA-000001" in response.data


def test_route_depuis_vente_refuse_client_de_passage(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    vente_id = _vente(client, catalogue, client_id=None, quantite=1)

    response = client.post(f"/factures/depuis-vente/{vente_id}", follow_redirects=True)
    assert response.status_code == 200
    assert "enregistré".encode() in response.data or "client de passage".encode() in response.data


def test_route_depuis_client_refuse_sans_permission_clients(client, login_seller, catalogue, app, db):
    # Un Vendeur (point_de_vente + caisse, pas "clients") ne doit pas
    # pouvoir générer une facture depuis l'historique d'un client en
    # devinant l'URL, même sans accès à la fiche client elle-même.
    client_id = _creer_client(db, app)
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    v1 = _vente(client, catalogue, client_id=client_id, quantite=1)

    response = client.post(f"/factures/depuis-client/{client_id}", data={"vente_ids": [v1]})
    assert response.status_code == 403


def test_route_depuis_client_agrege_plusieurs_tickets(client, login_admin, catalogue, app, db):
    client_id = _creer_client(db, app)
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    v1 = _vente(client, catalogue, client_id=client_id, quantite=1)
    v2 = _vente(client, catalogue, client_id=client_id, quantite=2)

    response = client.post(
        f"/factures/depuis-client/{client_id}",
        data={"vente_ids": [v1, v2]},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"FA-000001" in response.data

    from app.models import Facture

    with app.app_context():
        facture = Facture.query.first()
        assert facture.total == 8000 + 16000
        assert len(facture.ventes) == 2


def test_ticket_deja_facture_non_reselectionnable_sur_la_fiche_client(client, login_admin, catalogue, app, db):
    client_id = _creer_client(db, app)
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    v1 = _vente(client, catalogue, client_id=client_id, quantite=1)

    client.post("/factures/depuis-client/" + str(client_id), data={"vente_ids": [v1]})

    fiche = client.get(f"/clients/{client_id}")
    assert fiche.status_code == 200
    assert b"facture FA-000001" in fiche.data


def test_pdf_et_page_facture_accessibles(client, login_admin, catalogue, app, db):
    client_id = _creer_client(db, app)
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    v1 = _vente(client, catalogue, client_id=client_id, quantite=1)
    client.post("/factures/depuis-client/" + str(client_id), data={"vente_ids": [v1]})

    from app.models import Facture

    with app.app_context():
        facture_id = Facture.query.first().id

    page = client.get(f"/factures/{facture_id}")
    assert page.status_code == 200
    assert b"FA-000001" in page.data
    assert b"vendor/logo/akiba-logo.png" in page.data

    pdf = client.get(f"/factures/{facture_id}/pdf")
    assert pdf.status_code == 200
    assert pdf.mimetype == "application/pdf"
    assert int(pdf.headers["Content-Length"]) > 1000  # PDF non vide (logo inclus)


def test_voir_facture_refuse_a_un_profil_sans_pdv_ni_clients(client, login_admin, catalogue, app, db):
    # Un Comptable (seulement "rapports") ne doit pas pouvoir consulter une
    # facture arbitraire en devinant son URL.
    from app.extensions import db as _db
    from app.models import Facture, Profile, SubProfile

    client_id = _creer_client(db, app)
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    v1 = _vente(client, catalogue, client_id=client_id, quantite=1)
    client.post("/factures/depuis-client/" + str(client_id), data={"vente_ids": [v1]})

    with app.app_context():
        facture_id = Facture.query.first().id
        comptable = Profile(code="comptable_test", name="Comptable Test", icon="calculate")
        comptable.permissions = ["rapports"]
        _db.session.add(comptable)
        _db.session.flush()
        sous_profil = SubProfile(profile_id=comptable.id, full_name="Compta Test")
        sous_profil.set_pin("1234")
        _db.session.add(sous_profil)
        _db.session.commit()
        sous_profil_id = sous_profil.id
        profil_id = comptable.id

    client.post("/auth/deconnexion")
    client.post(f"/auth/profil/{profil_id}/utilisateur/{sous_profil_id}", data={"pin": "1234"})

    response = client.get(f"/factures/{facture_id}")
    assert response.status_code == 403


def test_admin_parametres_legaux_sont_repris_sur_la_facture(client, login_admin, catalogue, app, db):
    reponse = client.post(
        "/admin/parametres-legaux",
        data={"raison_sociale": "Association Akiba", "nif": "1234567", "stat": "STAT987"},
    )
    assert reponse.status_code == 302

    client_id = _creer_client(db, app)
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    v1 = _vente(client, catalogue, client_id=client_id, quantite=1)
    client.post("/factures/depuis-client/" + str(client_id), data={"vente_ids": [v1]})

    from app.models import Facture

    with app.app_context():
        facture = Facture.query.first()
        assert facture.emetteur_raison_sociale == "Association Akiba"
        assert facture.emetteur_nif == "1234567"
