def test_achats_requires_permission(client, login_seller):
    # Le Vendeur n'a que "point_de_vente" et "caisse" (§3.1 spec) : les Achats
    # sont réservés à Responsable/Administrateur.
    assert client.get("/achats/").status_code == 403
    assert client.get("/achats/nouveau").status_code == 403


def test_formulaire_achat_preselectionne_le_moyen_de_paiement_par_defaut(client, login_admin, catalogue, db):
    from app.models import MoyenPaiement

    moyen = db.session.get(MoyenPaiement, catalogue["moyen_paiement_id"])
    moyen.is_default = True
    db.session.commit()

    response = client.get("/achats/nouveau")
    assert response.status_code == 200
    assert f'selected value="{moyen.id}"'.encode() in response.data


def _achat_stock_payload(catalogue, quantite=5, prix_unitaire=1000):
    return {
        "type_achat": "stock",
        "fournisseur_id": "0",
        "date_achat": "2024-01-15",
        "poste_id": str(catalogue["poste_id"]),
        "projet_id": "0",
        "categorie_id": str(catalogue["categorie_id"]),
        "sous_categorie_id": "0",
        "produit_id": str(catalogue["produit_id"]),
        "quantite": str(quantite),
        "prix_unitaire": str(prix_unitaire),
        "origine": "pdv",
        "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
    }


def test_achat_stock_augmente_stock_et_debite_compte(client, login_admin, catalogue):
    payload = _achat_stock_payload(catalogue)
    payload["nom"] = "Réparation four"
    response = client.post("/achats/nouveau", data=payload)
    assert response.status_code == 302

    from app.models import Achat

    achat = Achat.query.first()
    assert achat.nom == "Réparation four"

    from app.extensions import db
    from app.models import CompteFinancier, MouvementStock, Produit

    produit = db.session.get(Produit, catalogue["produit_id"])
    assert produit.stock_quantite == 15  # 10 initial + 5 achetés

    mouvement = MouvementStock.query.filter_by(produit_id=produit.id, motif="achat").first()
    assert mouvement is not None
    assert mouvement.quantite == 5
    assert mouvement.type_mouvement == "entree"

    compte = db.session.get(CompteFinancier, catalogue["caisse_id"])
    assert compte.solde == -5000  # débité du montant de l'achat (5 x 1000)


def test_achat_depense_ne_touche_pas_stock(client, login_admin, catalogue):
    payload = {
        "type_achat": "depense",
        "fournisseur_id": "0",
        "date_achat": "2024-01-15",
        "poste_id": str(catalogue["poste_id"]),
        "projet_id": "0",
        "categorie_id": str(catalogue["categorie_id"]),
        "sous_categorie_id": "0",
        "produit_id": "0",
        "montant_total": "20000",
        "origine": "pdv",
        "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
    }
    response = client.post("/achats/nouveau", data=payload)
    assert response.status_code == 302

    from app.extensions import db
    from app.models import CompteFinancier, MouvementStock, Produit

    produit = db.session.get(Produit, catalogue["produit_id"])
    assert produit.stock_quantite == 10  # inchangé

    assert MouvementStock.query.filter_by(produit_id=produit.id).count() == 0

    compte = db.session.get(CompteFinancier, catalogue["caisse_id"])
    assert compte.solde == -20000


def test_achat_depense_payee_en_euros_debite_le_compte_dans_sa_devise(client, login_admin, catalogue, db):
    from app.models import CompteFinancier, MoyenPaiement, TauxChange

    compte_euro = CompteFinancier(name="Caisse Euro", devise="€")
    db.session.add(compte_euro)
    db.session.flush()
    moyen_euro = MoyenPaiement(name="Espèces Euro", compte_financier_id=compte_euro.id)
    db.session.add(moyen_euro)
    TauxChange.get().ariary_pour_un_euro = 4000
    db.session.commit()

    # Dépense de 20 000 Ar (montant_total, toujours en ariary) payée en
    # espèces euros au taux 1€ = 4000 Ar : le compte doit être débité de
    # 5 €, pas de "20 000 €".
    payload = {
        "type_achat": "depense",
        "fournisseur_id": "0",
        "date_achat": "2024-01-15",
        "poste_id": str(catalogue["poste_id"]),
        "projet_id": "0",
        "categorie_id": str(catalogue["categorie_id"]),
        "sous_categorie_id": "0",
        "produit_id": "0",
        "montant_total": "20000",
        "origine": "coffre_fort",
        "moyen_paiement_id": str(moyen_euro.id),
    }
    response = client.post("/achats/nouveau", data=payload)
    assert response.status_code == 302

    from app.models import Achat

    achat = Achat.query.order_by(Achat.id.desc()).first()
    assert achat.montant_total == 20000  # la dépense réelle reste en ariary

    db.session.refresh(compte_euro)
    assert compte_euro.solde == -5


def test_modifier_achat_ne_touche_pas_stock_ni_montant(client, login_admin, catalogue, db):
    client.post("/achats/nouveau", data=_achat_stock_payload(catalogue))
    from app.models import Achat, Produit

    achat = Achat.query.first()
    produit_avant = db.session.get(Produit, catalogue["produit_id"])
    stock_avant = produit_avant.stock_quantite
    montant_avant = achat.montant_total

    response = client.post(
        f"/achats/{achat.id}/modifier",
        data={
            "nom": "Bois corrigé",
            "poste_id": str(catalogue["poste_id"]),
            "projet_id": "0",
            "categorie_id": str(catalogue["categorie_id"]),
            "sous_categorie_id": "0",
            "fournisseur_id": "0",
            "date_achat": "2024-01-20",
            "observations": "Corrigé après coup",
        },
    )
    assert response.status_code == 302

    db.session.refresh(achat)
    produit_apres = db.session.get(Produit, catalogue["produit_id"])
    assert achat.nom == "Bois corrigé"
    assert achat.observations == "Corrigé après coup"
    assert achat.date_achat.isoformat() == "2024-01-20"
    assert achat.montant_total == montant_avant  # inchangé
    assert produit_apres.stock_quantite == stock_avant  # inchangé


def test_achat_stock_sans_produit_echoue(client, login_admin, catalogue):
    payload = _achat_stock_payload(catalogue)
    payload["produit_id"] = "0"

    response = client.post("/achats/nouveau", data=payload)
    assert response.status_code == 200  # reste sur le formulaire, pas de redirect

    from app.models import Achat

    assert Achat.query.count() == 0


def test_creer_modele_recurrent_depense(client, login_admin, catalogue):
    response = client.post(
        "/achats/recurrents",
        data={
            "nom": "Wifi mensuel",
            "type_achat": "depense",
            "fournisseur_id": "0",
            "poste_id": str(catalogue["poste_id"]),
            "projet_id": "0",
            "categorie_id": str(catalogue["categorie_id"]),
            "sous_categorie_id": "0",
            "produit_id": "0",
            "montant_habituel": "150000",
            "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
        },
    )
    assert response.status_code == 302

    from app.models import AchatRecurrent

    modele = AchatRecurrent.query.filter_by(nom="Wifi mensuel").first()
    assert modele is not None
    assert modele.type_achat == "depense"
    assert modele.montant_habituel == 150000


def test_formulaire_achat_preremplit_depuis_le_modele(client, login_admin, catalogue):
    client.post(
        "/achats/recurrents",
        data={
            "nom": "Bois de chauffe",
            "type_achat": "stock",
            "fournisseur_id": "0",
            "poste_id": str(catalogue["poste_id"]),
            "projet_id": "0",
            "categorie_id": str(catalogue["categorie_id"]),
            "sous_categorie_id": "0",
            "produit_id": str(catalogue["produit_id"]),
            "quantite_habituelle": "10",
            "prix_unitaire_habituel": "2000",
            "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
        },
    )
    from app.models import AchatRecurrent

    modele = AchatRecurrent.query.filter_by(nom="Bois de chauffe").first()

    response = client.get(f"/achats/nouveau?modele={modele.id}")
    assert response.status_code == 200
    assert b'value="10"' in response.data
    assert b'value="2000"' in response.data
    assert b"Bois de chauffe" in response.data


def test_archiver_modele_recurrent_le_retire_des_raccourcis(client, login_admin, catalogue):
    client.post(
        "/achats/recurrents",
        data={
            "nom": "Quincaillerie",
            "type_achat": "depense",
            "fournisseur_id": "0",
            "poste_id": str(catalogue["poste_id"]),
            "projet_id": "0",
            "categorie_id": str(catalogue["categorie_id"]),
            "sous_categorie_id": "0",
            "produit_id": "0",
            "montant_habituel": "30000",
            "moyen_paiement_id": "0",
        },
    )
    from app.models import AchatRecurrent

    modele = AchatRecurrent.query.filter_by(nom="Quincaillerie").first()

    client.get("/achats/recurrents")  # consomme le message flash de création
    client.post(f"/achats/recurrents/{modele.id}/archiver")

    from app.extensions import db

    db.session.refresh(modele)
    assert modele.is_archived is True

    response = client.get("/achats/")
    assert b"Quincaillerie" not in response.data


def test_achat_depense_sans_montant_est_refuse(client, login_admin, catalogue):
    payload = {
        "type_achat": "depense",
        "fournisseur_id": "0",
        "date_achat": "2024-01-15",
        "poste_id": str(catalogue["poste_id"]),
        "projet_id": "0",
        "categorie_id": str(catalogue["categorie_id"]),
        "sous_categorie_id": "0",
        "produit_id": "0",
        "montant_total": "",
        "origine": "pdv",
        "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
    }
    response = client.post("/achats/nouveau", data=payload)
    assert response.status_code == 200  # ré-affiche le formulaire, pas de redirection

    from app.models import Achat

    assert Achat.query.count() == 0


def test_achat_pdv_ouvre_le_tiroir(client, login_admin, catalogue, monkeypatch):
    appels = []
    monkeypatch.setattr("app.caisse.services.ouvrir_tiroir", lambda nom: appels.append(nom))

    payload = _achat_stock_payload(catalogue)
    response = client.post("/achats/nouveau", data=payload)
    assert response.status_code == 302
    assert len(appels) == 1


def test_achat_compte_akiba_najamais_ouvrir_le_tiroir(client, login_admin, catalogue, db, monkeypatch):
    from app.models import CompteFinancier, MoyenPaiement

    compte_akiba = CompteFinancier(name="Compte Akiba Test", devise="Ar", is_compte_akiba=True)
    db.session.add(compte_akiba)
    db.session.flush()
    moyen_akiba = MoyenPaiement(name="Espèces Ariary", compte_financier_id=compte_akiba.id, visible_pdv=False)
    db.session.add(moyen_akiba)
    db.session.commit()

    appels = []
    monkeypatch.setattr("app.caisse.services.ouvrir_tiroir", lambda nom: appels.append(nom))

    payload = _achat_stock_payload(catalogue)
    payload["origine"] = "coffre_fort"
    payload["moyen_paiement_id"] = str(moyen_akiba.id)
    response = client.post("/achats/nouveau", data=payload)
    assert response.status_code == 302
    assert appels == []


def test_achat_origine_incoherente_avec_le_moyen_est_refusee(client, login_admin, catalogue):
    payload = _achat_stock_payload(catalogue)
    payload["origine"] = "coffre_fort"  # mais moyen_paiement_id reste le moyen PDV (physique)
    response = client.post("/achats/nouveau", data=payload)
    assert response.status_code == 200

    from app.models import Achat

    assert Achat.query.count() == 0
