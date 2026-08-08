def test_pos_index_redirects_to_ouverture_without_session(client, login_seller, catalogue):
    response = client.get("/pos/")
    assert response.status_code == 302
    assert response.headers["Location"] == "/caisse/ouverture"


def test_pos_index_renders_catalogue_when_session_open(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.get("/pos/")
    assert response.status_code == 200
    assert b"Tablette Chocolat 70%" in response.data
    assert b"vendor/logo/akiba-picto.png" in response.data  # rond de la barre PDV


def test_pos_index_expose_le_taux_de_change_et_la_devise_des_moyens(client, login_seller, catalogue, db):
    from app.models import TauxChange

    TauxChange.get()  # crée la ligne par défaut (4800)

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.get("/pos/")
    assert response.status_code == 200
    assert b'"ariaryPourUnEuro": 4800' in response.data
    assert b'"devise": "Ar"' in response.data


def test_pos_index_expose_le_type_client_pour_le_tarif_automatique(client, login_seller, catalogue, db):
    from app.models import Client

    c = Client(type_client="adherent", nom="Adhérent Test")
    db.session.add(c)
    db.session.commit()

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.get("/pos/")
    assert response.status_code == 200
    assert b'"typeClient": "adherent"' in response.data


def test_pos_index_shows_recent_sales(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    client.post("/pos/vente", json=_checkout_payload(catalogue, quantite=1))

    response = client.get("/pos/")
    assert response.status_code == 200
    assert b"Ticket #1" in response.data
    assert "8 000".encode() in response.data or b"8000" in response.data


def _checkout_payload(catalogue, quantite=2, montant=None):
    total = montant if montant is not None else 8000 * quantite
    return {
        "type_tarif_id": catalogue["type_tarif_id"],
        "lignes": [{"produit_id": catalogue["produit_id"], "quantite": quantite, "remise": 0, "offert": False}],
        "paiements": [{"moyen_paiement_id": catalogue["moyen_paiement_id"], "montant": total}],
    }


def test_checkout_creates_vente_and_updates_stock_and_solde(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})

    response = client.post("/pos/vente", json=_checkout_payload(catalogue, quantite=2))
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True

    from app.extensions import db
    from app.models import CompteFinancier, Produit, Vente

    produit = db.session.get(Produit, catalogue["produit_id"])
    assert produit.stock_quantite == 8  # 10 - 2

    compte = db.session.get(CompteFinancier, catalogue["caisse_id"])
    assert compte.solde == 16000

    vente = Vente.query.order_by(Vente.id.desc()).first()
    assert vente.total == 16000
    assert vente.created_by_name == "Sarah"

    receipt = client.get(body["redirect"])
    assert receipt.status_code == 200
    assert b"Tablette Chocolat 70%" in receipt.data
    assert "Client suivant".encode() in receipt.data  # popup "vente suivante" (fresh=1)
    assert b"vendor/logo/akiba-logo.png" in receipt.data


def test_recu_sans_fresh_ne_montre_pas_le_popup(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.post("/pos/vente", json=_checkout_payload(catalogue, quantite=1))
    vente_id = response.get_json()["redirect"].split("/")[-1].split("?")[0]

    receipt = client.get(f"/pos/vente/{vente_id}")
    assert receipt.status_code == 200
    assert "Client suivant".encode() not in receipt.data


def test_checkout_rejects_insufficient_stock(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})

    response = client.post("/pos/vente", json=_checkout_payload(catalogue, quantite=99, montant=99 * 8000))
    assert response.status_code == 400
    assert "Stock insuffisant" in response.get_json()["error"]

    from app.extensions import db
    from app.models import Produit

    produit = db.session.get(Produit, catalogue["produit_id"])
    assert produit.stock_quantite == 10  # inchangé


def test_checkout_rejects_payment_mismatch(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})

    response = client.post("/pos/vente", json=_checkout_payload(catalogue, quantite=2, montant=1000))
    assert response.status_code == 400
    assert "ne correspond pas" in response.get_json()["error"]


def test_checkout_without_open_session_fails(client, login_seller, catalogue):
    response = client.post("/pos/vente", json=_checkout_payload(catalogue))
    assert response.status_code == 400


def test_produit_stock_illimite_ne_decremente_pas_et_ignore_la_rupture(client, login_seller, catalogue, db):
    from app.models import Produit, TypeTarif

    produit = db.session.get(Produit, catalogue["produit_id"])
    produit.stock_illimite = True
    produit.stock_quantite = 0  # déjà "en rupture" au sens classique
    db.session.commit()
    assert produit.statut_stock == "illimite"

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.post("/pos/vente", json=_checkout_payload(catalogue, quantite=50))
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    db.session.refresh(produit)
    assert produit.stock_quantite == 0  # inchangé, jamais décrémenté

    from app.models import MouvementStock

    assert MouvementStock.query.filter_by(produit_id=produit.id, motif="vente").count() == 0


def test_pos_index_propose_le_prix_calcule_par_rabais(client, login_seller, catalogue, app, db):
    # Un produit sans prix "adhérent" saisi à la main, mais avec un prix de
    # référence et un tarif Adhérent à rabais actif, doit quand même
    # apparaître vendable à ce tarif dans le PDV (pas seulement au tarif
    # standard) — le calcul automatique doit être exposé au front, pas
    # seulement utilisé côté serveur à l'encaissement.
    from app.models import Produit, TypeTarif

    tarif_adherent = TypeTarif(
        code="adherent", label="Adhérent", ordre=2, pourcentage_rabais=10, rabais_actif=True
    )
    db.session.add(tarif_adherent)
    produit = db.session.get(Produit, catalogue["produit_id"])
    produit.prix_reference = 5050
    db.session.commit()

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.get("/pos/")
    assert response.status_code == 200
    # 5050 - 10% = 4545, arrondi à la centaine supérieure = 4600.
    assert b'"adherent": 4600' in response.data


def test_pos_nav_masque_caisse_et_comptes_sans_le_droit_caisse(client, login_admin, catalogue, app, db):
    # La session est ouverte par un profil avec "caisse" (login_admin), puis
    # un profil "point_de_vente" seul (sans "caisse") l'utilise pour vendre
    # — les icônes Caisse/Comptes ne doivent pas apparaître pour lui.
    from app.models import Profile

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    client.post("/auth/deconnexion")

    with app.app_context():
        profil = Profile(code="vendeur_seul_test", name="Vendeur Seul Test", icon="point_of_sale")
        profil.permissions = ["point_de_vente"]
        db.session.add(profil)
        db.session.commit()
        from app.models import SubProfile

        sous_profil = SubProfile(profile_id=profil.id, full_name="Vendeur Seul")
        sous_profil.set_pin("4321")
        db.session.add(sous_profil)
        db.session.commit()
        profil_id, sous_profil_id = profil.id, sous_profil.id

    client.post(f"/auth/profil/{profil_id}/utilisateur/{sous_profil_id}", data={"pin": "4321"})

    response = client.get("/pos/")
    assert response.status_code == 200
    assert b'title="Caisse' not in response.data
    assert b'title="Comptes' not in response.data


def test_pos_index_expose_le_code_barres_des_produits(client, login_seller, catalogue, app, db):
    from app.models import Produit

    produit = db.session.get(Produit, catalogue["produit_id"])
    produit.code_barres = "3760123456789"
    db.session.commit()

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.get("/pos/")
    assert response.status_code == 200
    assert b'"codeBarres": "3760123456789"' in response.data


def test_vente_article_offert_genere_un_mouvement_de_stock_motif_offert(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})

    payload = {
        "type_tarif_id": catalogue["type_tarif_id"],
        "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 1, "remise": 0, "offert": True}],
        "paiements": [],
    }
    response = client.post("/pos/vente", json=payload)
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    from app.models import MouvementStock

    assert MouvementStock.query.filter_by(
        produit_id=catalogue["produit_id"], motif="offert", type_mouvement="sortie"
    ).count() == 1
    assert MouvementStock.query.filter_by(produit_id=catalogue["produit_id"], motif="vente").count() == 0


def test_vente_article_paye_garde_le_motif_vente(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})

    payload = {
        "type_tarif_id": catalogue["type_tarif_id"],
        "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 1, "remise": 0, "offert": False}],
        "paiements": [{"moyen_paiement_id": catalogue["moyen_paiement_id"], "montant": 8000}],
    }
    client.post("/pos/vente", json=payload)

    from app.models import MouvementStock

    assert MouvementStock.query.filter_by(produit_id=catalogue["produit_id"], motif="vente").count() == 1
    assert MouvementStock.query.filter_by(produit_id=catalogue["produit_id"], motif="offert").count() == 0


def _creer_moyen_euro(db, taux=4800):
    from app.models import CompteFinancier, MoyenPaiement, TauxChange

    compte = CompteFinancier(name="Caisse Euro", devise="€", is_caisse_physique=True)
    db.session.add(compte)
    db.session.flush()
    moyen = MoyenPaiement(name="Espèces Euro", compte_financier_id=compte.id)
    db.session.add(moyen)

    taux_change = TauxChange.get()
    taux_change.ariary_pour_un_euro = taux
    db.session.commit()
    return compte, moyen


def test_paiement_en_euros_credite_le_compte_dans_sa_devise(client, login_seller, catalogue, db):
    # Ticket à 8 000 Ar, payé en 2 € au taux 1€ = 4000 Ar : le compte Euro
    # doit recevoir 2 € (pas "8000 €", le bug historique).
    compte_euro, moyen_euro = _creer_moyen_euro(db, taux=4000)

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    payload = {
        "type_tarif_id": catalogue["type_tarif_id"],
        "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 1, "remise": 0, "offert": False}],
        "paiements": [{"moyen_paiement_id": moyen_euro.id, "montant": 2}],
    }
    response = client.post("/pos/vente", json=payload)
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    from app.extensions import db as _db

    _db.session.refresh(compte_euro)
    assert compte_euro.solde == 2  # bien 2 €, pas 8000


def test_paiement_en_euros_insuffisant_est_refuse(client, login_seller, catalogue, db):
    # 1 € à 4000 Ar/€ = 4000 Ar, insuffisant pour un ticket à 8000 Ar.
    _, moyen_euro = _creer_moyen_euro(db, taux=4000)

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    payload = {
        "type_tarif_id": catalogue["type_tarif_id"],
        "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 1, "remise": 0, "offert": False}],
        "paiements": [{"moyen_paiement_id": moyen_euro.id, "montant": 1}],
    }
    response = client.post("/pos/vente", json=payload)
    assert response.status_code == 400
    assert "ne correspond pas" in response.get_json()["error"]


def test_paiement_combine_ariary_et_euros(client, login_seller, catalogue, db):
    # Ticket 8000 Ar réglé en 4000 Ar espèces + 1 € (= 4000 Ar au taux 4000).
    compte_euro, moyen_euro = _creer_moyen_euro(db, taux=4000)

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    payload = {
        "type_tarif_id": catalogue["type_tarif_id"],
        "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 1, "remise": 0, "offert": False}],
        "paiements": [
            {"moyen_paiement_id": catalogue["moyen_paiement_id"], "montant": 4000},
            {"moyen_paiement_id": moyen_euro.id, "montant": 1},
        ],
    }
    response = client.post("/pos/vente", json=payload)
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    from app.extensions import db as _db
    from app.models import CompteFinancier

    _db.session.refresh(compte_euro)
    assert compte_euro.solde == 1
    compte_ariary = _db.session.get(CompteFinancier, catalogue["caisse_id"])
    assert compte_ariary.solde == 4000


def _creer_produit_prix_libre(db, catalogue, name="Pourboire"):
    from app.models import Produit

    produit = Produit(
        name=name,
        categorie_id=catalogue["categorie_id"],
        poste_id=catalogue["poste_id"],
        stock_illimite=True,
        prix_libre=True,
    )
    db.session.add(produit)
    db.session.commit()
    return produit


def test_pos_index_expose_le_poste_et_le_prix_libre_des_produits(client, login_seller, catalogue, db):
    _creer_produit_prix_libre(db, catalogue)

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.get("/pos/")
    assert response.status_code == 200
    assert b'"prixLibre": true' in response.data
    assert b'"posteId":' in response.data


def test_vente_avec_prix_libre_utilise_le_montant_saisi(client, login_seller, catalogue, db):
    produit = _creer_produit_prix_libre(db, catalogue)

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    payload = {
        "type_tarif_id": catalogue["type_tarif_id"],
        "lignes": [{"produit_id": produit.id, "quantite": 1, "remise": 0, "offert": False, "prix_unitaire": 2500}],
        "paiements": [{"moyen_paiement_id": catalogue["moyen_paiement_id"], "montant": 2500}],
    }
    response = client.post("/pos/vente", json=payload)
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    from app.models import Vente

    vente = Vente.query.order_by(Vente.id.desc()).first()
    assert vente.total == 2500
    assert vente.lignes[0].prix_unitaire == 2500


def test_vente_avec_prix_libre_sans_montant_est_refusee(client, login_seller, catalogue, db):
    produit = _creer_produit_prix_libre(db, catalogue)

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    payload = {
        "type_tarif_id": catalogue["type_tarif_id"],
        "lignes": [{"produit_id": produit.id, "quantite": 1, "remise": 0, "offert": False}],
        "paiements": [{"moyen_paiement_id": catalogue["moyen_paiement_id"], "montant": 0}],
    }
    response = client.post("/pos/vente", json=payload)
    assert response.status_code == 400
    assert "Montant invalide" in response.get_json()["error"]
