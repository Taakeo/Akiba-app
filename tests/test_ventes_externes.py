def _ajouter_compte_akiba(db):
    from app.models import CompteFinancier

    compte = CompteFinancier(name="Compte Akiba", devise="Ar", is_compte_akiba=True)
    db.session.add(compte)
    db.session.commit()
    return compte.id


def test_ventes_externes_requires_permission(client, login_seller):
    # Le Vendeur n'a que "point_de_vente" et "caisse" — les Ventes externes
    # sont réservées à Administrateur/Responsable (nouveau droit dédié).
    assert client.get("/ventes-externes/").status_code == 403
    assert client.get("/ventes-externes/nouveau").status_code == 403


def test_responsable_a_le_droit_ventes_externes_par_defaut(client, app, db):
    from app.models import Profile, SubProfile

    with app.app_context():
        profile = Profile(code="responsable", name="Responsable", icon="manage_accounts")
        profile.permissions = [
            "point_de_vente", "caisse", "achats", "ventes_externes", "stocks",
            "production", "rapports", "rh", "clients",
        ]
        db.session.add(profile)
        db.session.commit()
        sub = SubProfile(profile_id=profile.id, full_name="Resp")
        sub.set_pin("4242")
        db.session.add(sub)
        db.session.commit()
        profile_id, sub_id = profile.id, sub.id

    client.post(f"/auth/profil/{profile_id}/utilisateur/{sub_id}", data={"pin": "4242"})
    assert client.get("/ventes-externes/").status_code == 200


def _payload_libre(catalogue, moyen_id, montant_total=15000):
    return {
        "client_id": "0",
        "client_nom": "Jean Rakoto",
        "date_vente": "2024-01-15",
        "poste_id": str(catalogue["poste_id"]),
        "projet_id": "0",
        "categorie_id": str(catalogue["categorie_id"]),
        "sous_categorie_id": "0",
        "produit_id": "0",
        "montant_total": str(montant_total),
        "moyen_paiement_id": str(moyen_id),
        "observations": "Vente d'une table en bois",
    }


def test_vente_externe_libre_credite_toujours_le_compte_akiba(client, login_admin, catalogue, db):
    # Le moyen de paiement choisi est celui de la caisse PDV physique — le
    # crédit doit quand même atterrir sur le Compte Akiba, jamais sur la
    # caisse PDV (retour utilisateur : "peu importe [le moyen], le compte à
    # créditer c'est le compte de Akiba/coffre fort pas le pdv").
    compte_akiba_id = _ajouter_compte_akiba(db)

    payload = _payload_libre(catalogue, catalogue["moyen_paiement_id"])
    response = client.post("/ventes-externes/nouveau", data=payload)
    assert response.status_code == 302

    from app.models import CompteFinancier, VenteExterne

    vente = VenteExterne.query.first()
    assert vente is not None
    assert vente.montant_total == 15000
    assert vente.client_nom == "Jean Rakoto"
    assert vente.produit_id is None

    compte_akiba = db.session.get(CompteFinancier, compte_akiba_id)
    assert compte_akiba.solde == 15000

    caisse_pdv = db.session.get(CompteFinancier, catalogue["caisse_id"])
    assert caisse_pdv.solde == 0  # jamais touchée par une vente externe


def test_vente_externe_produit_catalogue_deduit_le_stock(client, login_admin, catalogue, db):
    compte_akiba_id = _ajouter_compte_akiba(db)

    payload = {
        "client_id": "0",
        "client_nom": "Ferme locale",
        "date_vente": "2024-01-15",
        "poste_id": str(catalogue["poste_id"]),
        "projet_id": "0",
        "categorie_id": str(catalogue["categorie_id"]),
        "sous_categorie_id": "0",
        "produit_id": str(catalogue["produit_id"]),
        "quantite": "3",
        "prix_unitaire": "2000",
        "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
    }
    response = client.post("/ventes-externes/nouveau", data=payload)
    assert response.status_code == 302

    from app.models import CompteFinancier, MouvementStock, Produit

    produit = db.session.get(Produit, catalogue["produit_id"])
    assert produit.stock_quantite == 7  # 10 initial - 3 vendus

    mouvement = MouvementStock.query.filter_by(produit_id=produit.id, motif="vente").first()
    assert mouvement is not None
    assert mouvement.quantite == 3
    assert mouvement.type_mouvement == "sortie"
    assert mouvement.reference_type == "vente_externe"

    compte_akiba = db.session.get(CompteFinancier, compte_akiba_id)
    assert compte_akiba.solde == 6000  # 3 x 2000


def test_vente_externe_refuse_sans_client(client, login_admin, catalogue, db):
    _ajouter_compte_akiba(db)

    payload = _payload_libre(catalogue, catalogue["moyen_paiement_id"])
    payload["client_nom"] = ""
    response = client.post("/ventes-externes/nouveau", data=payload)
    assert response.status_code == 200  # ré-affiche le formulaire, pas de redirection

    from app.models import VenteExterne

    assert VenteExterne.query.count() == 0


def test_vente_externe_refuse_sans_compte_akiba_configure(client, login_admin, catalogue):
    # Aucun compte marqué is_compte_akiba=True dans ce test -> message d'erreur
    # explicite plutôt qu'un crash ou une perte silencieuse de l'argent.
    payload = _payload_libre(catalogue, catalogue["moyen_paiement_id"])
    response = client.post("/ventes-externes/nouveau", data=payload)
    assert response.status_code == 200

    from app.models import VenteExterne

    assert VenteExterne.query.count() == 0
