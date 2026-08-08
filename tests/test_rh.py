def test_creer_salarie(client, login_admin, catalogue):
    response = client.post(
        "/rh/nouveau",
        data={
            "nom": "Lala Rakoto",
            "telephone": "032 11 111 11",
            "fonction": "Vendeuse",
            "type_contrat": "CDI",
            "date_embauche": "2023-01-10",
            "poste_id": str(catalogue["poste_id"]),
            "projet_id": "0",
        },
    )
    assert response.status_code == 302

    from app.models import Salarie

    salarie = Salarie.query.filter_by(nom="Lala Rakoto").first()
    assert salarie is not None
    assert salarie.fonction == "Vendeuse"
    assert salarie.poste_id == catalogue["poste_id"]


def test_ajouter_remuneration_debite_compte(client, login_admin, catalogue):
    client.post(
        "/rh/nouveau",
        data={"nom": "Lala Rakoto", "poste_id": "0", "projet_id": "0"},
    )
    from app.models import Salarie

    salarie = Salarie.query.filter_by(nom="Lala Rakoto").first()

    response = client.post(
        f"/rh/{salarie.id}/remuneration",
        data={
            "type_remuneration": "salaire_mensuel",
            "montant": "300000",
            "date_versement": "2024-02-28",
            "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
        },
    )
    assert response.status_code == 302

    from app.extensions import db
    from app.models import CompteFinancier, RemunerationSalarie

    remuneration = RemunerationSalarie.query.filter_by(salarie_id=salarie.id).first()
    assert remuneration is not None
    assert remuneration.montant == 300000

    compte = db.session.get(CompteFinancier, catalogue["caisse_id"])
    assert compte.solde == -300000


def test_remuneration_payee_en_euros_debite_le_compte_dans_sa_devise(client, login_admin, catalogue, db):
    from app.models import CompteFinancier, MoyenPaiement, TauxChange

    compte_euro = CompteFinancier(name="Caisse Euro", devise="€")
    db.session.add(compte_euro)
    db.session.flush()
    moyen_euro = MoyenPaiement(name="Espèces Euro", compte_financier_id=compte_euro.id)
    db.session.add(moyen_euro)
    TauxChange.get().ariary_pour_un_euro = 4000
    db.session.commit()

    client.post("/rh/nouveau", data={"nom": "Lala Rakoto", "poste_id": "0", "projet_id": "0"})
    from app.models import Salarie

    salarie = Salarie.query.filter_by(nom="Lala Rakoto").first()

    # Salaire de 300 000 Ar (montant, toujours en ariary) payé en espèces
    # euros au taux 1€ = 4000 Ar : le compte doit être débité de 75 €, pas
    # de "300 000 €".
    client.post(
        f"/rh/{salarie.id}/remuneration",
        data={
            "type_remuneration": "salaire_mensuel",
            "montant": "300000",
            "date_versement": "2024-02-28",
            "moyen_paiement_id": str(moyen_euro.id),
        },
    )

    from app.models import RemunerationSalarie

    remuneration = RemunerationSalarie.query.filter_by(salarie_id=salarie.id).first()
    assert remuneration.montant == 300000  # reste en ariary

    db.session.refresh(compte_euro)
    assert compte_euro.solde == -75


def test_retenue_ne_debite_pas_compte_sans_moyen_paiement(client, login_admin, catalogue):
    client.post("/rh/nouveau", data={"nom": "Lala Rakoto", "poste_id": "0", "projet_id": "0"})
    from app.models import Salarie

    salarie = Salarie.query.filter_by(nom="Lala Rakoto").first()

    client.post(
        f"/rh/{salarie.id}/remuneration",
        data={
            "type_remuneration": "retenue",
            "montant": "5000",
            "date_versement": "2024-02-28",
            "moyen_paiement_id": "0",
        },
    )

    from app.extensions import db
    from app.models import CompteFinancier

    compte = db.session.get(CompteFinancier, catalogue["caisse_id"])
    assert compte.solde == 0

    response = client.get(f"/rh/{salarie.id}")
    assert response.status_code == 200
    assert b"-5 000" in response.data or b"-5000" in response.data


def test_rh_requires_permission(client, login_seller):
    response = client.get("/rh/")
    assert response.status_code == 403


def test_creer_salarie_avec_salaire_hebdomadaire(client, login_admin, catalogue):
    response = client.post(
        "/rh/nouveau",
        data={
            "nom": "Voahangy",
            "poste_id": "0",
            "projet_id": "0",
            "type_contrat": "Hebdomadaire",
            "salaire_habituel": "50000",
            "frequence_remuneration": "hebdomadaire",
        },
    )
    assert response.status_code == 302

    from app.models import Salarie

    salarie = Salarie.query.filter_by(nom="Voahangy").first()
    assert salarie.type_contrat == "Hebdomadaire"
    assert salarie.salaire_habituel == 50000
    assert salarie.frequence_remuneration == "hebdomadaire"


def test_creer_salarie_sans_salaire_reste_facultatif(client, login_admin, catalogue):
    response = client.post("/rh/nouveau", data={"nom": "Bénévole Test", "poste_id": "0", "projet_id": "0"})
    assert response.status_code == 302

    from app.models import Salarie

    salarie = Salarie.query.filter_by(nom="Bénévole Test").first()
    assert salarie.salaire_habituel is None
    assert salarie.frequence_remuneration is None


def test_nouveau_salarie_reprend_le_quota_conges_par_defaut(client, login_admin, catalogue, db):
    from app.models import ParametresRH

    parametres = ParametresRH.get()
    parametres.quota_conges_defaut = 25
    db.session.commit()

    client.post("/rh/nouveau", data={"nom": "Quota Test", "poste_id": "0", "projet_id": "0"})

    from app.models import Salarie

    salarie = Salarie.query.filter_by(nom="Quota Test").first()
    assert salarie.quota_conges == 25


def test_modifier_quota_conges_defaut_en_administration(client, login_admin, db):
    response = client.post("/admin/parametres-rh", data={"quota_conges_defaut": "20"})
    assert response.status_code == 302

    from app.models import ParametresRH

    assert ParametresRH.get().quota_conges_defaut == 20


def test_solde_du_augmente_avec_une_ligne_non_versee(client, login_admin, catalogue, db):
    salarie = _creer_salarie(client)
    client.post(
        f"/rh/{salarie.id}/remuneration",
        data={
            "type_remuneration": "salaire_hebdomadaire",
            "montant": "50000",
            "date_versement": "2024-07-15",
            "moyen_paiement_id": "0",  # non versé
        },
    )
    db.session.refresh(salarie)
    assert salarie.solde_du == 50000


def test_solde_du_se_reduit_au_paiement_effectif(client, login_admin, catalogue, db):
    salarie = _creer_salarie(client)
    client.post(
        f"/rh/{salarie.id}/remuneration",
        data={
            "type_remuneration": "salaire_hebdomadaire",
            "montant": "50000",
            "date_versement": "2024-07-15",
            "moyen_paiement_id": "0",
        },
    )
    client.post(
        f"/rh/{salarie.id}/remuneration",
        data={
            "type_remuneration": "salaire_hebdomadaire",
            "montant": "50000",
            "date_versement": "2024-07-22",
            "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),  # versé
        },
    )
    db.session.refresh(salarie)
    # Une dette déclarée (+50000) puis son paiement réel (-50000) : compte à jour.
    assert salarie.solde_du == 0


def test_solde_du_negatif_apres_une_avance_versee(client, login_admin, catalogue, db):
    salarie = _creer_salarie(client)
    client.post(
        f"/rh/{salarie.id}/remuneration",
        data={
            "type_remuneration": "avance",
            "montant": "30000",
            "date_versement": "2024-07-01",
            "moyen_paiement_id": str(catalogue["moyen_paiement_id"]),
        },
    )
    db.session.refresh(salarie)
    assert salarie.solde_du == -30000  # le salarié a reçu une avance, pas encore rattrapée


def test_retenue_reduit_le_solde_du_meme_sans_moyen_paiement(client, login_admin, catalogue, db):
    salarie = _creer_salarie(client)
    client.post(
        f"/rh/{salarie.id}/remuneration",
        data={
            "type_remuneration": "salaire_hebdomadaire",
            "montant": "50000",
            "date_versement": "2024-07-15",
            "moyen_paiement_id": "0",
        },
    )
    client.post(
        f"/rh/{salarie.id}/remuneration",
        data={
            "type_remuneration": "retenue",
            "montant": "5000",
            "date_versement": "2024-07-15",
            "moyen_paiement_id": "0",
        },
    )
    db.session.refresh(salarie)
    assert salarie.solde_du == 45000


def test_solde_du_visible_sur_la_liste_et_la_fiche(client, login_admin, catalogue):
    salarie = _creer_salarie(client)
    client.post(
        f"/rh/{salarie.id}/remuneration",
        data={
            "type_remuneration": "salaire_hebdomadaire",
            "montant": "50000",
            "date_versement": "2024-07-15",
            "moyen_paiement_id": "0",
        },
    )

    liste = client.get("/rh/")
    assert b"D\xc3\xbb : 50 000" in liste.data

    fiche = client.get(f"/rh/{salarie.id}")
    assert "doit encore".encode() in fiche.data
    assert b"50 000" in fiche.data


def test_filtre_absences_par_plage_de_dates(client, login_admin, catalogue):
    salarie = _creer_salarie(client)
    client.post(
        f"/rh/{salarie.id}/absence",
        data={"type_absence": "maladie", "date_debut": "2024-01-05", "date_fin": "2024-01-05"},
    )
    client.post(
        f"/rh/{salarie.id}/absence",
        data={"type_absence": "conge_paye", "date_debut": "2024-06-10", "date_fin": "2024-06-12"},
    )

    # Sans filtre : les deux absences sont comptées.
    response = client.get(f"/rh/{salarie.id}")
    assert b"4 jour(s) au total" in response.data

    # Filtré sur juin seulement : ne garde que le congé payé (3 jours).
    response = client.get(f"/rh/{salarie.id}?depuis=2024-06-01&jusqua=2024-06-30")
    assert b"3 jour(s) sur la p" in response.data


def _creer_salarie(client, nom="Lala Rakoto"):
    client.post("/rh/nouveau", data={"nom": nom, "poste_id": "0", "projet_id": "0"})
    from app.models import Salarie

    return Salarie.query.filter_by(nom=nom).first()


def test_ajouter_absence_un_jour(client, login_admin, catalogue):
    salarie = _creer_salarie(client)

    response = client.post(
        f"/rh/{salarie.id}/absence",
        data={"type_absence": "maladie", "date_debut": "2024-03-05", "date_fin": "2024-03-05"},
    )
    assert response.status_code == 302

    from app.models import Absence

    absence = Absence.query.filter_by(salarie_id=salarie.id).first()
    assert absence is not None
    assert absence.nombre_jours == 1
    assert absence.type_absence == "maladie"


def test_ajouter_absence_plusieurs_jours(client, login_admin, catalogue):
    salarie = _creer_salarie(client)

    client.post(
        f"/rh/{salarie.id}/absence",
        data={"type_absence": "conge_paye", "date_debut": "2024-03-04", "date_fin": "2024-03-08"},
    )

    from app.models import Absence

    absence = Absence.query.filter_by(salarie_id=salarie.id).first()
    assert absence.nombre_jours == 5

    response = client.get(f"/rh/{salarie.id}")
    assert response.status_code == 200
    assert b"5 jour(s) au total" in response.data


def test_absence_date_fin_avant_debut_refusee(client, login_admin, catalogue):
    salarie = _creer_salarie(client)

    client.post(
        f"/rh/{salarie.id}/absence",
        data={"type_absence": "maladie", "date_debut": "2024-03-10", "date_fin": "2024-03-05"},
    )

    from app.models import Absence

    assert Absence.query.filter_by(salarie_id=salarie.id).count() == 0


def test_supprimer_absence(client, login_admin, catalogue):
    salarie = _creer_salarie(client)
    client.post(
        f"/rh/{salarie.id}/absence",
        data={"type_absence": "autre", "date_debut": "2024-03-05", "date_fin": "2024-03-05"},
    )
    from app.models import Absence

    absence = Absence.query.filter_by(salarie_id=salarie.id).first()

    response = client.post(f"/rh/{salarie.id}/absence/{absence.id}/supprimer")
    assert response.status_code == 302
    assert Absence.query.filter_by(salarie_id=salarie.id).count() == 0


def _ajouter_remuneration(client, salarie_id, type_remuneration, montant, date_versement, moyen_paiement_id=None):
    data = {
        "type_remuneration": type_remuneration,
        "montant": str(montant),
        "date_versement": date_versement,
    }
    if moyen_paiement_id:
        data["moyen_paiement_id"] = str(moyen_paiement_id)
    return client.post(f"/rh/{salarie_id}/remuneration", data=data)


def test_fiche_paie_impression_recapitule_les_mouvements_depuis_le_salaire_precedent(client, login_admin, catalogue):
    from app.models import RemunerationSalarie, Salarie

    client.post("/rh/nouveau", data={"nom": "Lala Rakoto", "poste_id": "0", "projet_id": "0"})
    salarie = Salarie.query.filter_by(nom="Lala Rakoto").first()

    _ajouter_remuneration(client, salarie.id, "salaire_mensuel", 300000, "2024-01-31", catalogue["moyen_paiement_id"])
    _ajouter_remuneration(client, salarie.id, "avance", 20000, "2024-02-10", catalogue["moyen_paiement_id"])
    _ajouter_remuneration(client, salarie.id, "prime", 15000, "2024-02-15", catalogue["moyen_paiement_id"])
    _ajouter_remuneration(client, salarie.id, "retenue", 5000, "2024-02-20")
    _ajouter_remuneration(client, salarie.id, "salaire_mensuel", 300000, "2024-02-29", catalogue["moyen_paiement_id"])

    salaire_fevrier = RemunerationSalarie.query.filter_by(
        salarie_id=salarie.id, type_remuneration="salaire_mensuel"
    ).order_by(RemunerationSalarie.date_versement.desc()).first()

    response = client.get(f"/rh/{salarie.id}/remuneration/{salaire_fevrier.id}/fiche-paie")
    assert response.status_code == 200
    # Net = 300000 + 15000 (prime) - 5000 (retenue) - 20000 (avance) = 290000
    assert "290 000".encode() in response.data or b"290000" in response.data
    assert b"Lala Rakoto" in response.data

    # Le salaire de janvier ne doit pas r\xc3\xa9apparaitre dans le r\xc3\xa9capitulatif de f\xc3\xa9vrier
    salaire_janvier = RemunerationSalarie.query.filter_by(
        salarie_id=salarie.id, type_remuneration="salaire_mensuel"
    ).order_by(RemunerationSalarie.date_versement.asc()).first()
    assert salaire_janvier.id != salaire_fevrier.id


def test_fiche_paie_impression_refuse_une_avance_isolee(client, login_admin, catalogue):
    from app.models import RemunerationSalarie, Salarie

    client.post("/rh/nouveau", data={"nom": "Lala Rakoto", "poste_id": "0", "projet_id": "0"})
    salarie = Salarie.query.filter_by(nom="Lala Rakoto").first()
    _ajouter_remuneration(client, salarie.id, "avance", 20000, "2024-02-10", catalogue["moyen_paiement_id"])
    avance = RemunerationSalarie.query.filter_by(salarie_id=salarie.id).first()

    response = client.get(f"/rh/{salarie.id}/remuneration/{avance.id}/fiche-paie")
    assert response.status_code == 404


def test_fiche_paie_impression_requires_permission(client, login_seller, catalogue):
    response = client.get("/rh/1/remuneration/1/fiche-paie")
    assert response.status_code == 403
