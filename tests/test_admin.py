def test_admin_requires_admin_permission(client, login_seller):
    response = client.get("/admin/")
    assert response.status_code == 403


def test_admin_index_accessible_to_admin(client, login_admin):
    response = client.get("/admin/")
    assert response.status_code == 200
    assert b"vendor/logo/akiba-picto.png" in response.data  # logo du menu principal


def test_modifier_taux_de_change_en_administration(client, login_admin, db):
    response = client.post("/admin/taux-change", data={"ariary_pour_un_euro": "5000"})
    assert response.status_code == 302

    from app.models import TauxChange

    assert TauxChange.get().ariary_pour_un_euro == 5000


def test_taux_de_change_par_defaut(client, login_admin, db):
    from app.models import TauxChange

    assert TauxChange.get().ariary_pour_un_euro == 4800


def test_create_and_archive_poste(client, login_admin):
    response = client.post("/admin/postes", data={"name": "Agriculture", "icon": "agriculture"})
    assert response.status_code == 302

    from app.models import Poste

    poste = Poste.query.filter_by(name="Agriculture").first()
    assert poste is not None
    assert poste.is_archived is False

    response = client.post(f"/admin/postes/{poste.id}/archiver")
    assert response.status_code == 302

    from app.extensions import db

    db.session.refresh(poste)
    assert poste.is_archived is True


def test_moyens_paiement_requiert_permission_admin(client, login_seller):
    response = client.get("/admin/moyens-paiement")
    assert response.status_code == 403


def test_creer_et_archiver_moyen_paiement(client, login_admin, catalogue):
    from app.models import CompteFinancier

    compte = CompteFinancier.query.first()
    response = client.post(
        "/admin/moyens-paiement",
        data={"name": "Chèque", "compte_financier_id": str(compte.id)},
    )
    assert response.status_code == 302

    from app.models import MoyenPaiement

    moyen = MoyenPaiement.query.filter_by(name="Chèque").first()
    assert moyen is not None
    assert moyen.is_archived is False
    assert moyen.compte_financier_id == compte.id

    response = client.post(f"/admin/moyens-paiement/{moyen.id}/archiver")
    assert response.status_code == 302

    from app.extensions import db

    db.session.refresh(moyen)
    assert moyen.is_archived is True


def test_archiver_moyen_paiement_par_defaut_le_desactive(client, login_admin, catalogue):
    from app.extensions import db
    from app.models import MoyenPaiement

    moyen = db.session.get(MoyenPaiement, catalogue["moyen_paiement_id"])
    moyen.is_default = True
    db.session.commit()

    client.post(f"/admin/moyens-paiement/{moyen.id}/archiver")

    db.session.refresh(moyen)
    assert moyen.is_archived is True
    assert moyen.is_default is False


def test_moyen_paiement_archive_disparait_des_choix_pdv(client, login_seller, catalogue):
    from app.extensions import db
    from app.models import MoyenPaiement

    import json

    moyen = db.session.get(MoyenPaiement, catalogue["moyen_paiement_id"])
    # Motif exact de l'entrée JSON pour ce moyen (voir pos/index.html) :
    # {"id": 1, "name": "...", "devise": "Ar"} — le nom JSON-échappé évite un
    # faux positif sur un autre objet (ex. un produit) qui aurait le même id.
    motif = f'"id": {moyen.id}, "name": {json.dumps(moyen.name)}, "devise"'.encode()

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    response = client.get("/pos/")
    assert motif in response.data

    # Archivage direct en base (équivalent au clic admin, testé séparément
    # ci-dessus) pour isoler ce qu'on vérifie ici : la disparition côté PDV.
    moyen.is_archived = True
    db.session.commit()

    response = client.get("/pos/")
    assert motif not in response.data


def test_create_categorie_and_sous_categorie(client, login_admin, db):
    from app.models import Poste

    poste = Poste(name="Boutique")
    db.session.add(poste)
    db.session.commit()

    client.post(
        "/admin/categories",
        data={"poste_id": str(poste.id), "name": "Boutique", "icon": "storefront", "ordre": "0"},
    )

    from app.models import Categorie

    categorie = Categorie.query.filter_by(name="Boutique").first()
    assert categorie is not None

    response = client.post(
        "/admin/sous-categories",
        data={"categorie_id": str(categorie.id), "name": "Chocolaterie"},
    )
    assert response.status_code == 302

    from app.models import SousCategorie

    sous_categorie = SousCategorie.query.filter_by(name="Chocolaterie").first()
    assert sous_categorie is not None
    assert sous_categorie.categorie_id == categorie.id


def _setup_poste_categorie_tarif(db):
    from app.models import Categorie, Poste, TypeTarif

    poste = Poste(name="Boutique")
    tarif = TypeTarif(code="standard", label="Standard", ordre=1, is_default=True)
    db.session.add_all([poste, tarif])
    db.session.flush()
    categorie = Categorie(poste_id=poste.id, name="Boutique")
    db.session.add(categorie)
    db.session.commit()
    return poste, categorie, tarif


def test_create_produit_with_tarif(client, login_admin, app, db):
    with app.app_context():
        poste, categorie, tarif = _setup_poste_categorie_tarif(db)
        poste_id, categorie_id, tarif_id = poste.id, categorie.id, tarif.id

    response = client.post(
        "/admin/produits/nouveau",
        data={
            "name": "Miel d'Akiba",
            "poste_id": str(poste_id),
            "projet_id": "0",
            "categorie_id": str(categorie_id),
            "sous_categorie_id": "0",
            "unite": "unité",
            "stock_quantite": "15",
            f"prix_{tarif_id}": "15000",
        },
    )
    assert response.status_code == 302

    from app.models import Produit

    produit = Produit.query.filter_by(name="Miel d'Akiba").first()
    assert produit is not None
    assert produit.stock_quantite == 15
    assert produit.prix_pour("standard") == 15000


def test_produit_photo_upload_et_service(client, login_admin, app, db):
    import io

    with app.app_context():
        poste, categorie, tarif = _setup_poste_categorie_tarif(db)
        poste_id, categorie_id = poste.id, categorie.id

    response = client.post(
        "/admin/produits/nouveau",
        data={
            "name": "Miel avec photo",
            "poste_id": str(poste_id),
            "projet_id": "0",
            "categorie_id": str(categorie_id),
            "sous_categorie_id": "0",
            "unite": "unité",
            "stock_quantite": "5",
            "photo": (io.BytesIO(b"donnees-image-factices"), "miel.png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302

    from app.models import Produit

    produit = Produit.query.filter_by(name="Miel avec photo").first()
    assert produit.photo_path == "miel.png"

    photo_response = client.get(f"/admin/produits/{produit.id}/photo")
    assert photo_response.status_code == 200
    assert photo_response.data == b"donnees-image-factices"


def test_produit_photo_requiert_connexion(client):
    response = client.get("/admin/produits/1/photo")
    assert response.status_code in (302, 401)  # redirigé vers la connexion


def test_produit_stock_illimite_ignore_stock_quantite(client, login_admin, app, db):
    with app.app_context():
        poste, categorie, tarif = _setup_poste_categorie_tarif(db)
        poste_id, categorie_id = poste.id, categorie.id

    response = client.post(
        "/admin/produits/nouveau",
        data={
            "name": "Visite guidée",
            "poste_id": str(poste_id),
            "projet_id": "0",
            "categorie_id": str(categorie_id),
            "sous_categorie_id": "0",
            "unite": "unité",
            "stock_quantite": "0",
            "stock_illimite": "y",
        },
    )
    assert response.status_code == 302

    from app.models import Produit

    produit = Produit.query.filter_by(name="Visite guidée").first()
    assert produit.stock_illimite is True
    assert produit.statut_stock == "illimite"


def test_edit_produit_updates_tarif(client, login_admin, app, db):
    with app.app_context():
        poste, categorie, tarif = _setup_poste_categorie_tarif(db)
        from app.models import Produit

        produit = Produit(name="Café", poste_id=poste.id, categorie_id=categorie.id, stock_quantite=5)
        db.session.add(produit)
        db.session.commit()
        produit_id, tarif_id, poste_id, categorie_id = produit.id, tarif.id, poste.id, categorie.id

    response = client.post(
        f"/admin/produits/{produit_id}/modifier",
        data={
            "name": "Café moulu",
            "poste_id": str(poste_id),
            "projet_id": "0",
            "categorie_id": str(categorie_id),
            "sous_categorie_id": "0",
            "unite": "unité",
            "stock_quantite": "5",
            f"prix_{tarif_id}": "12000",
        },
    )
    assert response.status_code == 302

    from app.extensions import db as _db
    from app.models import Produit

    produit = _db.session.get(Produit, produit_id)
    assert produit.name == "Café moulu"
    assert produit.prix_pour("standard") == 12000


def test_create_utilisateur_genere_un_pin_a_4_chiffres(client, login_admin, admin_profile):
    response = client.post(
        "/admin/utilisateurs/nouveau",
        data={"profile_id": str(admin_profile), "full_name": "Lala"},
    )
    assert response.status_code == 200  # page "PIN généré", pas de redirect

    from app.models import SubProfile

    lala = SubProfile.query.filter_by(full_name="Lala").first()
    assert lala is not None

    import re

    pin_affiche = re.search(r">(\d{4})<", response.data.decode("utf-8"))
    assert pin_affiche is not None
    assert lala.check_pin(pin_affiche.group(1))


def test_suspend_reactivate_utilisateur(client, login_admin, admin_profile):
    client.post("/admin/utilisateurs/nouveau", data={"profile_id": str(admin_profile), "full_name": "Lala"})
    from app.models import SubProfile

    lala = SubProfile.query.filter_by(full_name="Lala").first()

    response = client.post(f"/admin/utilisateurs/{lala.id}/suspendre")
    assert response.status_code == 302

    from app.extensions import db

    db.session.refresh(lala)
    assert lala.is_active is False

    client.post(f"/admin/utilisateurs/{lala.id}/reactiver")
    db.session.refresh(lala)
    assert lala.is_active is True


def test_regenerer_pin(client, login_admin, admin_profile):
    client.post("/admin/utilisateurs/nouveau", data={"profile_id": str(admin_profile), "full_name": "Lala"})
    from app.models import SubProfile

    lala = SubProfile.query.filter_by(full_name="Lala").first()
    ancien_hash = lala.pin_hash

    response = client.post(f"/admin/utilisateurs/{lala.id}/pin/regenerer")
    assert response.status_code == 200

    from app.extensions import db

    db.session.refresh(lala)
    assert lala.pin_hash != ancien_hash

    import re

    pin_affiche = re.search(r">(\d{4})<", response.data.decode("utf-8"))
    assert lala.check_pin(pin_affiche.group(1))
    assert not lala.check_pin("4321")


def test_creer_tarif_devient_defaut_si_premier(client, login_admin, db):
    from app.models import TypeTarif

    response = client.post("/admin/tarifs", data={"label": "Standard"})
    assert response.status_code == 302

    tarif = TypeTarif.query.filter_by(label="Standard").first()
    assert tarif is not None
    assert tarif.code == "standard"
    assert tarif.is_default is True


def test_creer_second_tarif_ne_devient_pas_defaut(client, login_admin, db):
    from app.models import TypeTarif

    client.post("/admin/tarifs", data={"label": "Standard"})
    client.post("/admin/tarifs", data={"label": "Adhérent"})

    adherent = TypeTarif.query.filter_by(label="Adhérent").first()
    assert adherent.is_default is False
    assert adherent.code == "adherent"


def test_definir_tarif_par_defaut_bascule_lancien(client, login_admin, db):
    from app.models import TypeTarif

    client.post("/admin/tarifs", data={"label": "Standard"})
    client.post("/admin/tarifs", data={"label": "Adhérent"})
    standard = TypeTarif.query.filter_by(label="Standard").first()
    adherent = TypeTarif.query.filter_by(label="Adhérent").first()

    response = client.post(f"/admin/tarifs/{adherent.id}/definir-defaut")
    assert response.status_code == 302

    db.session.refresh(standard)
    db.session.refresh(adherent)
    assert adherent.is_default is True
    assert standard.is_default is False


def test_archiver_tarif_par_defaut_refuse(client, login_admin, db):
    from app.models import TypeTarif

    client.post("/admin/tarifs", data={"label": "Standard"})
    standard = TypeTarif.query.filter_by(label="Standard").first()

    client.post(f"/admin/tarifs/{standard.id}/archiver")

    db.session.refresh(standard)
    assert standard.is_archived is False


def test_archiver_dernier_tarif_actif_refuse(client, login_admin, db):
    from app.models import TypeTarif

    client.post("/admin/tarifs", data={"label": "Standard"})
    client.post("/admin/tarifs", data={"label": "Adhérent"})
    standard = TypeTarif.query.filter_by(label="Standard").first()
    adherent = TypeTarif.query.filter_by(label="Adhérent").first()

    # Bascule le défaut sur Adhérent puis archive Standard : il reste un
    # tarif actif (Adhérent), l'archivage doit donc réussir.
    client.post(f"/admin/tarifs/{adherent.id}/definir-defaut")
    client.post(f"/admin/tarifs/{standard.id}/archiver")
    db.session.refresh(standard)
    assert standard.is_archived is True

    # Mais on ne peut pas archiver le dernier tarif actif restant (Adhérent).
    client.post(f"/admin/tarifs/{adherent.id}/archiver")
    db.session.refresh(adherent)
    assert adherent.is_archived is False


def test_comptes_financiers_requiert_permission_admin(client, login_seller):
    response = client.get("/admin/comptes-financiers")
    assert response.status_code == 403


def test_ajuster_le_solde_dun_compte_cree_un_historique_trace(client, login_admin, catalogue):
    from app.models import CompteFinancier

    compte = CompteFinancier.query.first()
    solde_avant = compte.solde

    response = client.post(
        f"/admin/comptes-financiers/{compte.id}/ajuster",
        data={"nouveau_solde": "500000", "motif": "Solde de départ réel au lancement de l'application"},
    )
    assert response.status_code == 302

    from app.extensions import db

    db.session.refresh(compte)
    assert compte.solde == 500000

    from app.models import AjustementCompte

    ajustement = AjustementCompte.query.filter_by(compte_financier_id=compte.id).first()
    assert ajustement is not None
    assert ajustement.ancien_solde == solde_avant
    assert ajustement.nouveau_solde == 500000
    assert ajustement.motif == "Solde de départ réel au lancement de l'application"
    assert ajustement.created_by_name == "Admin"


def test_ajuster_le_solde_sans_motif_est_refuse(client, login_admin, catalogue):
    from app.models import CompteFinancier

    compte = CompteFinancier.query.first()
    solde_avant = compte.solde

    response = client.post(
        f"/admin/comptes-financiers/{compte.id}/ajuster",
        data={"nouveau_solde": "999999", "motif": ""},
    )
    assert response.status_code == 200  # re-rendu, formulaire invalide

    from app.extensions import db

    db.session.refresh(compte)
    assert compte.solde == solde_avant


def test_page_comptes_financiers_liste_les_comptes(client, login_admin, catalogue):
    response = client.get("/admin/comptes-financiers")
    assert response.status_code == 200
    assert "Ajuster le solde".encode() in response.data


def test_deux_postes_peuvent_avoir_une_categorie_de_meme_nom(db):
    from app.models import Categorie, Poste

    poste_a = Poste(name="Poste A")
    poste_b = Poste(name="Poste B")
    db.session.add_all([poste_a, poste_b])
    db.session.flush()

    db.session.add(Categorie(poste_id=poste_a.id, name="Salaires"))
    db.session.add(Categorie(poste_id=poste_b.id, name="Salaires"))
    db.session.commit()  # ne doit pas lever d'IntegrityError : unicité sur (poste_id, name)

    assert Categorie.query.filter_by(name="Salaires").count() == 2


def test_modifier_moyen_paiement_change_le_compte_finance(client, login_admin, catalogue, db):
    from app.models import CompteFinancier, MoyenPaiement

    compte_a = db.session.get(CompteFinancier, catalogue["caisse_id"])
    compte_b = CompteFinancier(name="Compte Mobile Money", devise="Ar")
    db.session.add(compte_b)
    db.session.commit()

    moyen = db.session.get(MoyenPaiement, catalogue["moyen_paiement_id"])
    assert moyen.compte_financier_id == compte_a.id

    response = client.post(
        f"/admin/moyens-paiement/{moyen.id}/modifier",
        data={"name": "Espèces Ariary", "compte_financier_id": str(compte_b.id), "ouvre_tiroir": "y"},
    )
    assert response.status_code == 302

    db.session.refresh(moyen)
    assert moyen.compte_financier_id == compte_b.id
    assert moyen.ouvre_tiroir is True


def test_modifier_moyen_paiement_requiert_permission_admin(client, login_seller, catalogue):
    response = client.get(f"/admin/moyens-paiement/{catalogue['moyen_paiement_id']}/modifier")
    assert response.status_code == 403


def test_creer_modifier_supprimer_compte_financier(client, login_admin, db):
    response = client.post(
        "/admin/comptes-financiers",
        data={"name": "Compte Test", "devise": "Ar", "visible_tableau_bord": "y"},
    )
    assert response.status_code == 302

    from app.models import CompteFinancier

    compte = CompteFinancier.query.filter_by(name="Compte Test").first()
    assert compte is not None
    assert compte.is_caisse_physique is False

    response = client.post(
        f"/admin/comptes-financiers/{compte.id}/modifier",
        data={"name": "Compte Test Modifié", "devise": "€", "visible_tableau_bord": "y"},
    )
    assert response.status_code == 302
    db.session.refresh(compte)
    assert compte.name == "Compte Test Modifié"
    assert compte.devise == "€"

    response = client.post(f"/admin/comptes-financiers/{compte.id}/supprimer")
    assert response.status_code == 302
    assert db.session.get(CompteFinancier, compte.id) is None


def test_supprimer_compte_financier_reference_est_bloque(client, login_admin, catalogue, db):
    from app.models import CompteFinancier

    compte = db.session.get(CompteFinancier, catalogue["caisse_id"])
    response = client.post(f"/admin/comptes-financiers/{compte.id}/supprimer", follow_redirects=True)
    assert response.status_code == 200
    assert "Impossible de supprimer".encode() in response.data
    assert db.session.get(CompteFinancier, compte.id) is not None


def test_masquer_un_compte_du_tableau_de_bord(client, login_admin, catalogue, db):
    from app.models import CompteFinancier

    compte = db.session.get(CompteFinancier, catalogue["caisse_id"])

    response = client.get("/")
    assert response.status_code == 200
    assert compte.name.encode() in response.data

    client.post(
        f"/admin/comptes-financiers/{compte.id}/modifier",
        data={
            "name": compte.name,
            "devise": compte.devise,
            "is_caisse_physique": "y",
            # visible_tableau_bord absent = décoché
        },
    )
    client.get("/")  # consomme le message flash "mis à jour" (contient le nom du compte)

    response = client.get("/")
    assert compte.name.encode() not in response.data


def test_deux_moyens_de_meme_nom_sur_des_comptes_differents(client, login_admin, catalogue, db):
    from app.models import CompteFinancier

    autre_compte = CompteFinancier(name="Autre Compte Ariary", devise="Ar")
    db.session.add(autre_compte)
    db.session.commit()

    response = client.post(
        "/admin/moyens-paiement",
        data={"name": "Espèces Ariary", "compte_financier_id": str(autre_compte.id)},
    )
    assert response.status_code == 302

    from app.models import MoyenPaiement

    assert MoyenPaiement.query.filter_by(name="Espèces Ariary").count() == 2
