def test_ouverture_requires_login(client):
    response = client.get("/caisse/ouverture")
    assert response.status_code == 302
    assert "/auth/" in response.headers["Location"]


def test_modifier_taux_de_change_depuis_la_caisse(client, login_seller, catalogue, db):
    response = client.post("/caisse/taux-change", data={"ariary_pour_un_euro": "5200"})
    assert response.status_code == 302

    from app.models import TauxChange

    assert TauxChange.get().ariary_pour_un_euro == 5200


def test_status_affiche_le_taux_de_change(client, login_seller, catalogue):
    response = client.get("/caisse/")
    assert response.status_code == 200
    assert b"Taux de change" in response.data


def test_comptes_ne_montre_plus_les_actions_de_session(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.get("/caisse/")
    assert response.status_code == 200
    assert "Clôturer la caisse".encode() not in response.data
    assert "Entrée / Sortie d'argent".encode() not in response.data


def test_pdv_caisse_montre_la_session_en_cours(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "10000"})
    response = client.get("/caisse/pdv")
    assert response.status_code == 200
    assert "Clôturer la caisse".encode() in response.data
    assert "Entrée / Sortie d'argent".encode() in response.data
    assert b"Session en cours" in response.data


def test_pdv_caisse_propose_ouverture_si_fermee(client, login_seller, catalogue):
    response = client.get("/caisse/pdv")
    assert response.status_code == 200
    assert "Caisse fermée".encode() in response.data
    assert "Ouvrir la caisse".encode() in response.data


def test_achat_en_especes_apparait_dans_historique_session_et_reduit_theorique(
    client, login_admin, catalogue, db
):
    client.post("/caisse/ouverture", data={"fond_ouverture": "20000"})

    client.post(
        "/achats/nouveau",
        data={
            "type_achat": "depense",
            "fournisseur_id": "0",
            "date_achat": "2024-01-15",
            "poste_id": str(catalogue["poste_id"]),
            "projet_id": "0",
            "categorie_id": str(catalogue["categorie_id"]),
            "sous_categorie_id": "0",
            "produit_id": "0",
            "montant_total": "3000",
            "origine": "pdv",
            "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
            "nom": "Quincaillerie",
        },
    )

    from app.models import Achat, CaisseSession

    session = CaisseSession.query.filter_by(statut="ouverte").first()
    achat = Achat.query.filter_by(nom="Quincaillerie").first()
    assert achat.caisse_session_id == session.id

    pdv_page = client.get("/caisse/pdv")
    assert b"Quincaillerie" in pdv_page.data

    from app.caisse.services import calculer_theorique

    resume = calculer_theorique(session)
    # 20000 (fond) - 3000 (achat en espèces) = 17000, sans aucune vente/mouvement.
    assert resume["depenses"] == 3000
    assert resume["theorique"] == 17000


def test_achat_hors_especes_najoute_pas_a_la_session(client, login_admin, catalogue, db):
    from app.models import CompteFinancier, MoyenPaiement

    autre_compte = CompteFinancier(name="Mobile Money Test", devise="Ar")
    db.session.add(autre_compte)
    db.session.flush()
    autre_moyen = MoyenPaiement(name="Mobile Money Test", compte_financier_id=autre_compte.id)
    db.session.add(autre_moyen)
    db.session.commit()

    client.post("/caisse/ouverture", data={"fond_ouverture": "20000"})
    client.post(
        "/achats/nouveau",
        data={
            "type_achat": "depense",
            "fournisseur_id": "0",
            "date_achat": "2024-01-15",
            "poste_id": str(catalogue["poste_id"]),
            "projet_id": "0",
            "categorie_id": str(catalogue["categorie_id"]),
            "sous_categorie_id": "0",
            "produit_id": "0",
            "montant_total": "3000",
            "origine": "coffre_fort",
            "moyen_paiement_id": str(autre_moyen.id),
        },
    )

    from app.models import Achat, CaisseSession

    session = CaisseSession.query.filter_by(statut="ouverte").first()
    achat = Achat.query.order_by(Achat.id.desc()).first()
    assert achat.caisse_session_id is None

    from app.caisse.services import calculer_theorique

    resume = calculer_theorique(session)
    assert resume["theorique"] == 20000  # inchangé, l'achat n'a pas touché la caisse physique


def test_ouverture_creates_session(client, login_seller, catalogue):
    response = client.post("/caisse/ouverture", data={"fond_ouverture": "50000"})
    assert response.status_code == 302

    from app.models import CaisseSession

    session = CaisseSession.query.filter_by(statut="ouverte").first()
    assert session is not None
    assert session.fond_ouverture == 50000
    assert session.ouverte_par_nom == "Sarah"


def test_cannot_open_twice(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "50000"})
    response = client.post("/caisse/ouverture", data={"fond_ouverture": "10000"}, follow_redirects=True)

    from app.models import CaisseSession

    assert CaisseSession.query.filter_by(statut="ouverte").count() == 1
    assert response.status_code == 200


def test_mouvement_credits_compte(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})

    response = client.post(
        "/caisse/mouvement",
        data={
            "type_mouvement": "entree",
            "origine": "pdv",
            "montant": "5000",
            "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
            "motif": "Apport de monnaie",
        },
    )
    assert response.status_code == 302

    from app.extensions import db
    from app.models import CompteFinancier

    compte = db.session.get(CompteFinancier, catalogue["caisse_id"])
    assert compte.solde == 5000


def test_fermeture_computes_ecart(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "10000"})
    client.post(
        "/caisse/mouvement",
        data={
            "type_mouvement": "entree",
            "origine": "pdv",
            "montant": "5000",
            "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
            "motif": "Apport",
        },
    )

    response = client.post(
        "/caisse/fermeture", data={"fond_reel": "14000", "montant_preleve": "0", "commentaire": "Manque 1000"}
    )
    assert response.status_code == 302

    from app.models import CaisseSession

    session = CaisseSession.query.order_by(CaisseSession.id.desc()).first()
    assert session.statut == "fermee"
    assert session.fond_theorique == 15000
    assert session.fond_reel == 14000
    assert session.ecart == -1000


def _autre_moyen(db, nom="Mobile Money Test", devise="Ar"):
    from app.models import CompteFinancier, MoyenPaiement

    compte = CompteFinancier(name=nom, devise=devise)
    db.session.add(compte)
    db.session.flush()
    moyen = MoyenPaiement(name=nom, compte_financier_id=compte.id)
    db.session.add(moyen)
    db.session.commit()
    return moyen


def test_resume_session_par_moyen_agrege_ventes_et_mouvements(client, login_seller, catalogue, db):
    from app.caisse.services import get_open_session, resume_session_par_moyen

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})

    client.post(
        "/pos/vente",
        json={
            "type_tarif_id": catalogue["type_tarif_id"],
            "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 1, "remise": 0, "offert": False}],
            "paiements": [{"moyen_paiement_id": catalogue["moyen_paiement_id"], "montant": 8000}],
        },
    )
    client.post(
        "/caisse/mouvement",
        data={
            "type_mouvement": "entree",
            "origine": "pdv",
            "montant": "2000",
            "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
            "motif": "Apport",
        },
    )

    session = get_open_session()
    resume = resume_session_par_moyen(session)
    caisse = next(r for r in resume if r["moyen"].id == catalogue["moyen_paiement_id"])

    assert caisse["encaissements_ventes"] == 8000
    assert caisse["entrees"] == 2000
    assert caisse["total"] == 10000


def test_resume_session_par_moyen_inclut_le_fond_de_caisse_sur_le_compte_physique(
    client, login_seller, catalogue, db
):
    """Régression : le fond de caisse initial doit être compté dans le
    résumé par moyen, sur la ligne du compte physique de la session — sinon
    ce tableau affichait un total différent de celui du bloc "Théorique"
    juste au-dessus, sur la même page, pour la même caisse."""
    from app.caisse.services import get_open_session, resume_session_par_moyen

    client.post("/caisse/ouverture", data={"fond_ouverture": "20000"})
    client.post(
        "/pos/vente",
        json={
            "type_tarif_id": catalogue["type_tarif_id"],
            "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 1, "remise": 0, "offert": False}],
            "paiements": [{"moyen_paiement_id": catalogue["moyen_paiement_id"], "montant": 8000}],
        },
    )

    session = get_open_session()
    resume = resume_session_par_moyen(session)
    caisse = next(r for r in resume if r["moyen"].id == catalogue["moyen_paiement_id"])

    assert caisse["fond_ouverture"] == 20000
    assert caisse["total"] == 28000  # 20000 (fond) + 8000 (vente)

    from app.caisse.services import calculer_theorique

    # Les deux blocs affichés sur la même page doivent toujours concorder.
    assert caisse["total"] == calculer_theorique(session)["theorique"]


def test_resume_session_par_moyen_ninclut_pas_le_fond_sur_les_autres_comptes(
    client, login_seller, catalogue, db
):
    from app.caisse.services import get_open_session, resume_session_par_moyen

    autre = _autre_moyen(db)
    client.post("/caisse/ouverture", data={"fond_ouverture": "20000"})

    session = get_open_session()
    resume = resume_session_par_moyen(session)
    entree_autre = next(r for r in resume if r["moyen"].id == autre.id)

    assert entree_autre["fond_ouverture"] == 0
    assert entree_autre["total"] == 0


def test_resume_session_par_moyen_inclut_un_moyen_sans_activite_a_zero(client, login_seller, catalogue, db):
    from app.caisse.services import get_open_session, resume_session_par_moyen

    autre = _autre_moyen(db)
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})

    session = get_open_session()
    resume = resume_session_par_moyen(session)
    entree_autre = next(r for r in resume if r["moyen"].id == autre.id)

    assert entree_autre["total"] == 0
    assert entree_autre["compte"].id == autre.compte_financier_id


def test_resume_session_par_moyen_inclut_les_achats_hors_especes(client, login_admin, catalogue, db):
    from app.caisse.services import get_open_session, resume_session_par_moyen

    autre = _autre_moyen(db)
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    client.post(
        "/achats/nouveau",
        data={
            "type_achat": "depense",
            "fournisseur_id": "0",
            "date_achat": "2024-01-15",
            "poste_id": str(catalogue["poste_id"]),
            "projet_id": "0",
            "categorie_id": str(catalogue["categorie_id"]),
            "sous_categorie_id": "0",
            "produit_id": "0",
            "montant_total": "1500",
            "origine": "coffre_fort",
            "moyen_paiement_id": str(autre.id),
        },
    )

    session = get_open_session()
    resume = resume_session_par_moyen(session)
    entree_autre = next(r for r in resume if r["moyen"].id == autre.id)

    # Contrairement à calculer_theorique() (caisse physique uniquement), le
    # résumé par moyen inclut bien un achat payé par un moyen non-espèces,
    # tant qu'il a eu lieu pendant la session.
    assert entree_autre["achats"] == 1500
    assert entree_autre["total"] == -1500


def test_pdv_affiche_le_resume_par_moyen_et_les_liens_de_transactions(client, login_seller, catalogue, db):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    client.post(
        "/pos/vente",
        json={
            "type_tarif_id": catalogue["type_tarif_id"],
            "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 1, "remise": 0, "offert": False}],
            "paiements": [{"moyen_paiement_id": catalogue["moyen_paiement_id"], "montant": 8000}],
        },
    )

    response = client.get("/caisse/pdv")
    assert response.status_code == 200
    assert "Compte de la session".encode() in response.data
    assert "Transactions et tickets de la session".encode() in response.data
    assert b'href="/pos/vente/1"' in response.data


def test_pdv_transactions_triees_par_vrai_datetime_pas_par_texte(client, login_admin, catalogue, db):
    """Régression : un tri par chaîne "JJ/MM HH:MM" mélangerait l'ordre dès
    qu'on change de mois (ex. "01/09" < "30/08" lexicographiquement). On
    vérifie ici que le tri reste correct même dans ce cas de figure."""
    from datetime import datetime, timezone

    from app.caisse.services import get_open_session
    from app.models import MouvementCaisse

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    session = get_open_session()

    ancien = MouvementCaisse(
        caisse_session_id=session.id,
        type_mouvement="entree",
        montant=1000,
        moyen_paiement_id=catalogue["moyen_paiement_id"],
        motif="Mouvement du 30 août",
        created_by_name="Admin",
        created_at=datetime(2024, 8, 30, 10, 0, tzinfo=timezone.utc),
    )
    recent = MouvementCaisse(
        caisse_session_id=session.id,
        type_mouvement="entree",
        montant=2000,
        moyen_paiement_id=catalogue["moyen_paiement_id"],
        motif="Mouvement du 1er septembre",
        created_by_name="Admin",
        created_at=datetime(2024, 9, 1, 10, 0, tzinfo=timezone.utc),
    )
    db.session.add_all([ancien, recent])
    db.session.commit()

    from app.caisse.routes import _construire_evenements_session

    events = _construire_evenements_session(session)
    titres = [e["titre"] for e in events]
    assert titres.index("Mouvement du 1er septembre") < titres.index("Mouvement du 30 août")


def test_pdv_naffiche_plus_le_bouton_test_ouvrir_le_tiroir(client, login_seller, catalogue):
    # Le bouton "Ouvrir le tiroir" du PDV était réservé aux tests — retiré
    # (retour utilisateur) ; seul le test depuis Administration subsiste.
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.get("/caisse/pdv")
    assert response.status_code == 200
    assert "Ouvrir le tiroir".encode() not in response.data


def test_route_ouvrir_tiroir_pdv_nexiste_plus(client, login_seller, catalogue):
    response = client.post("/caisse/ouvrir-tiroir")
    assert response.status_code == 404


def test_mouvement_avec_moyen_ouvre_tiroir_declenche_l_impression(client, login_seller, catalogue, monkeypatch):
    appels = []
    monkeypatch.setattr("app.caisse.services.ouvrir_tiroir", lambda nom: appels.append(nom))

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    # Le moyen "Espèces Ariary" du catalogue de test a ouvre_tiroir=True.
    client.post(
        "/caisse/mouvement",
        data={
            "type_mouvement": "entree",
            "origine": "pdv",
            "montant": "5000",
            "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
            "motif": "Apport de monnaie",
        },
    )
    assert appels == ["POS-80"]


def test_mouvement_avec_moyen_sans_ouvre_tiroir_ne_declenche_rien(client, login_seller, catalogue, db, monkeypatch):
    from app.models import CompteFinancier, MoyenPaiement

    appels = []
    monkeypatch.setattr("app.caisse.services.ouvrir_tiroir", lambda nom: appels.append(nom))

    compte = CompteFinancier(name="Orange Money Test", devise="Ar")
    db.session.add(compte)
    db.session.flush()
    moyen = MoyenPaiement(name="Orange Money Test", compte_financier_id=compte.id, ouvre_tiroir=False)
    db.session.add(moyen)
    db.session.commit()

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    client.post(
        "/caisse/mouvement",
        data={
            "type_mouvement": "entree",
            "origine": "coffre_fort",
            "montant": "5000",
            "moyen_paiement_id": str(moyen.id),
            "motif": "Apport",
        },
    )
    assert appels == []


def test_parametres_imprimante_get_et_post(client, login_admin, catalogue):
    response = client.get("/admin/parametres-imprimante")
    assert response.status_code == 200
    assert b"POS-80" in response.data

    response = client.post("/admin/parametres-imprimante", data={"nom_imprimante": "Xprinter XP-58"})
    assert response.status_code == 302

    from app.models import ParametresImprimante

    assert ParametresImprimante.get().nom_imprimante == "Xprinter XP-58"


def test_parametres_imprimante_tester_appelle_l_impression(client, login_admin, catalogue, monkeypatch):
    appels = []
    # ouvrir_tiroir est importé localement dans la route (import tardif) ;
    # on patch donc directement app.caisse.printer.ouvrir_tiroir, source
    # réelle utilisée par cet import local.
    monkeypatch.setattr("app.caisse.printer.ouvrir_tiroir", lambda nom: appels.append(nom))

    response = client.post("/admin/parametres-imprimante/tester", follow_redirects=True)
    assert response.status_code == 200
    assert appels == ["POS-80"]


def test_montant_en_ariary_identite_pour_ariary(app, db, catalogue):
    from app.caisse.services import montant_en_ariary
    from app.models import MoyenPaiement

    with app.app_context():
        moyen = db.session.get(MoyenPaiement, catalogue["moyen_paiement_id"])
        assert montant_en_ariary(moyen, 5000) == 5000


def test_montant_en_ariary_convertit_les_euros(app, db, catalogue):
    from app.caisse.services import montant_en_ariary
    from app.models import CompteFinancier, MoyenPaiement, TauxChange

    with app.app_context():
        compte = CompteFinancier(name="Caisse Euro", devise="€")
        db.session.add(compte)
        db.session.flush()
        moyen = MoyenPaiement(name="Espèces Euro", compte_financier_id=compte.id)
        db.session.add(moyen)
        TauxChange.get().ariary_pour_un_euro = 4800
        db.session.commit()

        assert montant_en_ariary(moyen, 10) == 48000


def test_montant_depuis_ariary_est_linverse(app, db, catalogue):
    from app.caisse.services import montant_depuis_ariary, montant_en_ariary
    from app.models import CompteFinancier, MoyenPaiement, TauxChange

    with app.app_context():
        compte = CompteFinancier(name="Caisse Euro", devise="€")
        db.session.add(compte)
        db.session.flush()
        moyen = MoyenPaiement(name="Espèces Euro", compte_financier_id=compte.id)
        db.session.add(moyen)
        TauxChange.get().ariary_pour_un_euro = 4800
        db.session.commit()

        assert montant_depuis_ariary(moyen, 48000) == 10
        assert montant_en_ariary(moyen, montant_depuis_ariary(moyen, 48000)) == 48000


def test_mouvement_refuse_si_lorigine_ne_correspond_pas_au_moyen(client, login_seller, catalogue):
    # "Espèces Ariary" (catalogue) est un compte physique -> déclarer
    # "coffre_fort" pour ce moyen doit être refusé, pas silencieusement
    # accepté sur le mauvais compte.
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})

    response = client.post(
        "/caisse/mouvement",
        data={
            "type_mouvement": "entree",
            "origine": "coffre_fort",
            "montant": "5000",
            "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
            "motif": "Test",
        },
    )
    assert response.status_code == 200  # re-rendu du formulaire, pas de redirection
    assert "ne correspond pas".encode() in response.data

    from app.extensions import db
    from app.models import CompteFinancier

    compte = db.session.get(CompteFinancier, catalogue["caisse_id"])
    assert compte.solde == 0  # rien n'a été enregistré


def test_mouvement_accepte_un_compte_coffre_fort_avec_la_bonne_origine(client, login_seller, catalogue, db):
    from app.models import CompteFinancier, MoyenPaiement

    compte = CompteFinancier(name="Orange Money Test", devise="Ar")
    db.session.add(compte)
    db.session.flush()
    moyen = MoyenPaiement(name="Orange Money Test", compte_financier_id=compte.id)
    db.session.add(moyen)
    db.session.commit()

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.post(
        "/caisse/mouvement",
        data={
            "type_mouvement": "entree",
            "origine": "coffre_fort",
            "montant": "5000",
            "moyen_paiement_id": str(moyen.id),
            "motif": "Apport",
        },
    )
    assert response.status_code == 302

    db.session.refresh(compte)
    assert compte.solde == 5000


def test_mouvement_sans_origine_est_refuse(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})

    response = client.post(
        "/caisse/mouvement",
        data={
            "type_mouvement": "entree",
            "montant": "5000",
            "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
            "motif": "Test",
        },
    )
    assert response.status_code == 200  # re-rendu, champ obligatoire manquant

    from app.extensions import db
    from app.models import CompteFinancier

    compte = db.session.get(CompteFinancier, catalogue["caisse_id"])
    assert compte.solde == 0


def test_page_mouvement_propose_le_choix_dorigine(client, login_seller, catalogue):
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.get("/caisse/mouvement")
    assert response.status_code == 200
    assert "Caisse PDV".encode() in response.data
    assert "coffre-fort".encode() in response.data


def test_fermeture_credite_compte_akiba_du_montant_preleve(client, login_admin, catalogue, db):
    from app.models import CompteFinancier

    compte_akiba = CompteFinancier(name="Compte Akiba Test", devise="Ar", is_compte_akiba=True)
    db.session.add(compte_akiba)
    db.session.commit()

    client.post("/caisse/ouverture", data={"fond_ouverture": "10000"})
    response = client.post(
        "/caisse/fermeture", data={"fond_reel": "10000", "montant_preleve": "7000", "commentaire": ""}
    )
    assert response.status_code == 302

    db.session.refresh(compte_akiba)
    assert compte_akiba.solde == 7000

    from app.extensions import db as _db
    from app.models import CompteFinancier as CF

    caisse = _db.session.get(CF, catalogue["caisse_id"])
    assert caisse.solde == -7000  # débité de ce qui a rejoint le Compte Akiba


def test_fermeture_montant_preleve_superieur_au_reel_est_refuse(client, login_admin, catalogue, db):
    from app.models import CompteFinancier

    compte_akiba = CompteFinancier(name="Compte Akiba Test", devise="Ar", is_compte_akiba=True)
    db.session.add(compte_akiba)
    db.session.commit()

    client.post("/caisse/ouverture", data={"fond_ouverture": "10000"})
    response = client.post(
        "/caisse/fermeture", data={"fond_reel": "5000", "montant_preleve": "9000", "commentaire": ""}
    )
    assert response.status_code == 200  # ré-affiche le formulaire

    from app.models import CaisseSession

    session = CaisseSession.query.order_by(CaisseSession.id.desc()).first()
    assert session.statut == "ouverte"  # pas clôturée


def test_ouverture_suivante_prerempli_avec_le_reliquat(client, login_admin, catalogue, db):
    from app.models import CompteFinancier

    compte_akiba = CompteFinancier(name="Compte Akiba Test", devise="Ar", is_compte_akiba=True)
    db.session.add(compte_akiba)
    db.session.commit()

    client.post("/caisse/ouverture", data={"fond_ouverture": "10000"})
    client.post("/caisse/fermeture", data={"fond_reel": "12000", "montant_preleve": "9000", "commentaire": ""})

    # 12000 réel - 9000 prélevé = 3000 restés dans le tiroir.
    response = client.get("/caisse/ouverture")
    assert response.status_code == 200
    assert b'value="3000"' in response.data
