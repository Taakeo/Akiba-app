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


def test_pos_index_expose_editurl_pour_administrateur(client, login_admin, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.get("/pos/")
    assert response.status_code == 200
    assert f'/admin/produits/{catalogue["produit_id"]}/modifier'.encode() in response.data
    # Navigation dans la même fenêtre (jamais window.open/_blank, retour
    # utilisateur : rien ne doit ouvrir un navigateur dans l'appli) : le lien
    # porte depuis=pdv pour que "Retour" et l'enregistrement ramènent au PDV.
    assert b"depuis=pdv" in response.data


def test_produit_modifier_depuis_pdv_ramene_au_pdv_apres_enregistrement(client, login_admin, catalogue):
    response = client.post(
        f"/admin/produits/{catalogue['produit_id']}/modifier?depuis=pdv",
        data={
            "name": "Tablette Chocolat 70% (v2)",
            "poste_id": str(catalogue["poste_id"]),
            "categorie_id": str(catalogue["categorie_id"]),
            "sous_categorie_id": "0",
            "projet_id": "0",
            "fournisseur_principal_id": "0",
            "packaging_produit_id": "0",
            "unite": "unité",
            "stock_quantite": "10",
            "depuis": "pdv",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/pos/"


def test_droit_produits_donne_acces_a_la_fiche_sans_ouvrir_tout_admin(client, app, db, catalogue):
    # Droit étroit et distinct de "admin" (retour utilisateur : "crée une
    # permission plus étroite juste pour ça") — donne accès au raccourci PDV
    # + aux routes produit elles-mêmes, mais jamais au reste du panneau
    # Administration (comptes, utilisateurs, réinitialisation...).
    from app.models import Profile, SubProfile

    with app.app_context():
        profile = Profile(code="responsable", name="Responsable", icon="manage_accounts")
        profile.permissions = ["point_de_vente", "caisse", "produits"]
        db.session.add(profile)
        db.session.commit()
        sub = SubProfile(profile_id=profile.id, full_name="Resp")
        sub.set_pin("4242")
        db.session.add(sub)
        db.session.commit()
        profile_id, sub_id = profile.id, sub.id

    client.post(f"/auth/profil/{profile_id}/utilisateur/{sub_id}", data={"pin": "4242"})
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})

    response = client.get("/pos/")
    assert response.status_code == 200
    assert f'/admin/produits/{catalogue["produit_id"]}/modifier'.encode() in response.data

    assert client.get(f'/admin/produits/{catalogue["produit_id"]}/modifier').status_code == 200
    assert client.get("/admin/produits").status_code == 200
    # Jamais le reste du panneau Admin :
    assert client.get("/admin/").status_code == 403
    assert client.get("/admin/reinitialisation").status_code == 403


def test_pos_index_najamais_editurl_pour_vendeur(client, login_seller, catalogue):
    # Le Vendeur n'a pas le droit "admin" par défaut — le raccourci fiche
    # produit ne doit jamais pointer vers un lien qui renverrait une 403.
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.get("/pos/")
    assert response.status_code == 200
    assert f'/admin/produits/{catalogue["produit_id"]}/modifier'.encode() not in response.data


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


def test_checkout_avec_remise_sur_une_ligne_reduit_le_total(client, login_seller, catalogue):
    # Remise ponctuelle en Ariary sur une ligne précise (distincte d'"offert")
    # — accessible à tout utilisateur du PDV.
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})

    payload = {
        "type_tarif_id": catalogue["type_tarif_id"],
        "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 2, "remise": 3000, "offert": False}],
        "paiements": [{"moyen_paiement_id": catalogue["moyen_paiement_id"], "montant": 13000}],
    }
    response = client.post("/pos/vente", json=payload)
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    from app.models import LigneVente, Vente

    vente = Vente.query.order_by(Vente.id.desc()).first()
    assert vente.total == 13000  # (8000 x 2) - 3000

    ligne = LigneVente.query.filter_by(vente_id=vente.id).first()
    assert ligne.remise == 3000
    assert ligne.total_ligne == 13000


def test_recu_sans_fresh_ne_montre_pas_le_popup(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.post("/pos/vente", json=_checkout_payload(catalogue, quantite=1))
    vente_id = response.get_json()["redirect"].split("/")[-1].split("?")[0]

    receipt = client.get(f"/pos/vente/{vente_id}")
    assert receipt.status_code == 200
    assert "Client suivant".encode() not in receipt.data


def test_checkout_autorise_la_vente_malgre_un_stock_insuffisant(client, login_seller, catalogue):
    """Retour utilisateur : un stock affiché à 0/insuffisant ne doit plus
    jamais bloquer une vente (inventaire pas à jour, pas une raison de
    refuser un client au comptoir) — mais le stock ne doit jamais devenir
    négatif pour autant (clampé à 0)."""
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})

    response = client.post("/pos/vente", json=_checkout_payload(catalogue, quantite=99, montant=99 * 8000))
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    from app.extensions import db
    from app.models import Produit

    produit = db.session.get(Produit, catalogue["produit_id"])
    assert produit.stock_quantite == 0  # jamais négatif, malgré 99 vendus pour 10 en stock


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


def test_paiement_en_euros_ignore_le_taux_de_change(client, login_seller, catalogue, db):
    """Retour utilisateur : un paiement en euros ne doit plus jamais être
    comparé/bloqué par le taux de change — le montant saisi est manuel et
    définitif, même très inférieur à l'équivalent théorique (ici 1 € à
    4000 Ar/€ = 4000 Ar, pour un ticket à 8000 Ar : la vente doit quand même
    passer, réglée intégralement par ce seul paiement)."""
    _, moyen_euro = _creer_moyen_euro(db, taux=4000)

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    payload = {
        "type_tarif_id": catalogue["type_tarif_id"],
        "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 1, "remise": 0, "offert": False}],
        "paiements": [{"moyen_paiement_id": moyen_euro.id, "montant": 1}],
    }
    response = client.post("/pos/vente", json=payload)
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    from app.models import Vente

    vente = Vente.query.order_by(Vente.id.desc()).first()
    assert vente.montant_credit == 0  # réglée intégralement, jamais mise à crédit


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


def test_pos_index_exclut_les_categories_sans_produit_vendable(client, login_seller, catalogue, db):
    # Retour sur la décision initiale de tout mélanger sans filtre (§ PDV) :
    # une catégorie purement comptable (aucun produit, ou seulement des
    # emballages non vendables) ne doit plus apparaître dans la barre de
    # catégories du PDV, même si son poste est par ailleurs un poste de vente.
    from app.models import Categorie, Produit

    categorie_comptable = Categorie(poste_id=catalogue["poste_id"], name="Salaires_boutique")
    db.session.add(categorie_comptable)
    db.session.flush()

    categorie_emballage_seul = Categorie(poste_id=catalogue["poste_id"], name="Emballages")
    db.session.add(categorie_emballage_seul)
    db.session.flush()
    db.session.add(
        Produit(
            name="Sachet tablette 20g",
            categorie_id=categorie_emballage_seul.id,
            poste_id=catalogue["poste_id"],
            vendable_pdv=False,
            stock_quantite=100,
        )
    )
    db.session.commit()

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.get("/pos/")
    assert response.status_code == 200
    assert b"Salaires_boutique" not in response.data
    assert b"Emballages" not in response.data
    assert b"Boutique" in response.data  # la catégorie du catalogue, qui a un vrai produit vendable


def test_pos_index_exclut_les_produits_non_vendables(client, login_seller, catalogue, db):
    # Un emballage (vendable_pdv=False) ne doit jamais apparaître au PDV — ce
    # sont des produits que la boutique utilise elle-même, pas des articles à
    # vendre (§ demande packaging).
    from app.models import Produit

    emballage = Produit(
        name="Sachet tablette 20g",
        categorie_id=catalogue["categorie_id"],
        poste_id=catalogue["poste_id"],
        vendable_pdv=False,
        stock_quantite=100,
    )
    db.session.add(emballage)
    db.session.commit()

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.get("/pos/")
    assert response.status_code == 200
    assert b"Sachet tablette 20g" not in response.data


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


# --- Corrections administrateur : annulation de vente + édition de classement ----


def test_annulation_requiert_le_droit_corrections(client, login_seller, catalogue):
    # Le Vendeur (point_de_vente + caisse) n'a pas le droit "corrections" —
    # il peut encaisser une vente mais jamais l'annuler ou en corriger le
    # classement.
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.post("/pos/vente", json=_checkout_payload(catalogue, quantite=1))
    vente_id = response.get_json()["redirect"].split("/")[-1].split("?")[0]

    assert client.post(f"/pos/vente/{vente_id}/annuler", data={"motif": "Doublon"}).status_code == 403
    assert client.get(f"/pos/vente/{vente_id}/modifier").status_code == 403


def test_responsable_a_le_droit_corrections_par_defaut(client, app, db, catalogue):
    from app.models import Profile, SubProfile

    with app.app_context():
        profile = Profile(code="responsable", name="Responsable", icon="manage_accounts")
        profile.permissions = ["point_de_vente", "caisse", "corrections"]
        db.session.add(profile)
        db.session.commit()
        sub = SubProfile(profile_id=profile.id, full_name="Resp")
        sub.set_pin("4242")
        db.session.add(sub)
        db.session.commit()
        profile_id, sub_id = profile.id, sub.id

    client.post(f"/auth/profil/{profile_id}/utilisateur/{sub_id}", data={"pin": "4242"})
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.post("/pos/vente", json=_checkout_payload(catalogue, quantite=1))
    vente_id = response.get_json()["redirect"].split("/")[-1].split("?")[0]

    assert client.get(f"/pos/vente/{vente_id}/modifier").status_code == 200


def test_annuler_vente_restaure_le_stock_et_le_compte(client, login_admin, catalogue, db):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.post("/pos/vente", json=_checkout_payload(catalogue, quantite=2))
    vente_id = response.get_json()["redirect"].split("/")[-1].split("?")[0]

    from app.models import CompteFinancier, Produit, Vente

    produit = db.session.get(Produit, catalogue["produit_id"])
    assert produit.stock_quantite == 8  # 10 - 2
    compte = db.session.get(CompteFinancier, catalogue["caisse_id"])
    assert compte.solde == 16000

    resp = client.post(f"/pos/vente/{vente_id}/annuler", data={"motif": "Saisie en double"})
    assert resp.status_code == 302

    db.session.refresh(produit)
    db.session.refresh(compte)
    assert produit.stock_quantite == 10  # rétabli
    assert compte.solde == 0  # rétabli

    vente = db.session.get(Vente, int(vente_id))
    assert vente.statut == "annulee"
    assert "Saisie en double" in vente.commentaire


def test_annuler_vente_refuse_sans_motif(client, login_admin, catalogue, db):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.post("/pos/vente", json=_checkout_payload(catalogue, quantite=1))
    vente_id = response.get_json()["redirect"].split("/")[-1].split("?")[0]

    resp = client.post(f"/pos/vente/{vente_id}/annuler", data={"motif": ""})
    assert resp.status_code == 302

    from app.models import Vente

    assert db.session.get(Vente, int(vente_id)).statut == "validee"


def test_annuler_vente_deja_annulee_est_refusee(client, login_admin, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.post("/pos/vente", json=_checkout_payload(catalogue, quantite=1))
    vente_id = response.get_json()["redirect"].split("/")[-1].split("?")[0]

    client.post(f"/pos/vente/{vente_id}/annuler", data={"motif": "Première annulation"})

    from app.extensions import db
    from app.models import CompteFinancier, Produit

    produit = db.session.get(Produit, catalogue["produit_id"])
    compte = db.session.get(CompteFinancier, catalogue["caisse_id"])
    stock_apres_premiere = produit.stock_quantite
    solde_apres_premiere = compte.solde

    client.post(f"/pos/vente/{vente_id}/annuler", data={"motif": "Deuxième tentative"})

    db.session.refresh(produit)
    db.session.refresh(compte)
    # Aucun double-rétablissement du stock/compte sur une vente déjà annulée.
    assert produit.stock_quantite == stock_apres_premiere
    assert compte.solde == solde_apres_premiere


def test_annuler_vente_exclue_du_theorique_de_caisse(client, login_admin, catalogue, db):
    from app.caisse.services import calculer_theorique

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.post("/pos/vente", json=_checkout_payload(catalogue, quantite=1))
    vente_id = response.get_json()["redirect"].split("/")[-1].split("?")[0]

    from app.models import CaisseSession

    session = CaisseSession.query.filter_by(statut="ouverte").first()
    assert calculer_theorique(session)["theorique"] == 8000  # fond 0 + 1 x 8000

    client.post(f"/pos/vente/{vente_id}/annuler", data={"motif": "Erreur de saisie"})

    db.session.refresh(session)
    assert calculer_theorique(session)["theorique"] == 0


def test_vente_modifier_corrige_le_classement_sans_toucher_stock_ni_montant(client, login_admin, catalogue, db):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.post("/pos/vente", json=_checkout_payload(catalogue, quantite=2))
    vente_id = int(response.get_json()["redirect"].split("/")[-1].split("?")[0])

    from app.models import Categorie, Poste, Produit, Vente

    autre_poste = Poste(name="Autre poste")
    db.session.add(autre_poste)
    db.session.flush()
    autre_categorie = Categorie(poste_id=autre_poste.id, name="Autre catégorie")
    db.session.add(autre_categorie)
    db.session.commit()

    vente = db.session.get(Vente, vente_id)
    ligne = vente.lignes[0]
    produit_avant = db.session.get(Produit, catalogue["produit_id"])
    stock_avant = produit_avant.stock_quantite
    total_avant = vente.total

    resp = client.post(
        f"/pos/vente/{vente_id}/modifier",
        data={
            "client_id": "0",
            "client_nom": "Client corrigé",
            "commentaire": "Reclassé après coup",
            f"poste_id_{ligne.id}": str(autre_poste.id),
            f"categorie_id_{ligne.id}": str(autre_categorie.id),
            f"sous_categorie_id_{ligne.id}": "0",
            f"projet_id_{ligne.id}": "0",
        },
    )
    assert resp.status_code == 302

    db.session.refresh(vente)
    db.session.refresh(ligne)
    produit_apres = db.session.get(Produit, catalogue["produit_id"])

    assert vente.client_nom == "Client corrigé"
    assert vente.commentaire == "Reclassé après coup"
    assert ligne.poste_id == autre_poste.id
    assert ligne.categorie_id == autre_categorie.id
    # Jamais touché par cette correction :
    assert vente.total == total_avant
    assert produit_apres.stock_quantite == stock_avant
