import io

from openpyxl import Workbook


def _workbook_bytes(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(
        [
            "Nom complet",
            "Téléphone",
            "Fonction",
            "Type de contrat",
            "Date d'embauche (JJ/MM/AAAA)",
            "Poste",
            "Projet",
            "Salaire habituel",
            "Fréquence de versement",
            "Quota de congés payés (jours/an)",
        ]
    )
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def test_importer_salaries_cree_les_lignes_valides(app, db, catalogue):
    from app.admin.import_excel import importer_salaries_excel
    from app.models import Salarie

    fichier = _workbook_bytes(
        [
            ["Rabe Andry", "034 00 000 00", "Vendeur", "CDI", "01/03/2024", "Boutique", "", 150000, "Mensuel", ""],
        ]
    )

    with app.app_context():
        resultat = importer_salaries_excel(fichier)

        assert resultat["crees"] == [(2, "Rabe Andry")]
        assert resultat["erreurs"] == []

        salarie = Salarie.query.filter_by(nom="Rabe Andry").first()
        assert salarie is not None
        assert salarie.type_contrat == "CDI"
        assert salarie.frequence_remuneration == "mensuel"
        assert salarie.salaire_habituel == 150000
        assert salarie.date_embauche is not None
        assert salarie.date_embauche.isoformat() == "2024-03-01"


def test_importer_salaries_ignore_les_doublons(app, db, catalogue):
    from app.admin.import_excel import importer_salaries_excel
    from app.models import Salarie

    with app.app_context():
        db.session.add(Salarie(nom="Rabe Andry"))
        db.session.commit()

    fichier = _workbook_bytes(
        [
            ["Rabe Andry", "", "", "", "", "", "", "", "", ""],
        ]
    )

    with app.app_context():
        resultat = importer_salaries_excel(fichier)
        assert resultat["crees"] == []
        assert len(resultat["ignores"]) == 1
        assert Salarie.query.filter_by(nom="Rabe Andry").count() == 1


def test_importer_salaries_signale_un_type_contrat_inconnu(app, db, catalogue):
    from app.admin.import_excel import importer_salaries_excel

    fichier = _workbook_bytes(
        [
            ["Nouveau salarié", "", "", "Alien", "", "", "", "", "", ""],
        ]
    )

    with app.app_context():
        resultat = importer_salaries_excel(fichier)
        assert resultat["crees"] == []
        assert len(resultat["erreurs"]) == 1
        assert "Alien" in resultat["erreurs"][0][1]


def test_importer_salaries_signale_une_date_invalide(app, db, catalogue):
    from app.admin.import_excel import importer_salaries_excel

    fichier = _workbook_bytes(
        [
            ["Nouveau salarié", "", "", "", "31 fevrier", "", "", "", "", ""],
        ]
    )

    with app.app_context():
        resultat = importer_salaries_excel(fichier)
        assert resultat["crees"] == []
        assert len(resultat["erreurs"]) == 1
        assert "embauche" in resultat["erreurs"][0][1]


def test_importer_salaries_applique_le_quota_par_defaut(app, db, catalogue):
    from app.admin.import_excel import importer_salaries_excel
    from app.models import ParametresRH, Salarie

    fichier = _workbook_bytes(
        [
            ["Nouveau salarié", "", "", "", "", "", "", "", "", ""],
        ]
    )

    with app.app_context():
        importer_salaries_excel(fichier)
        salarie = Salarie.query.filter_by(nom="Nouveau salarié").first()
        assert salarie.quota_conges == ParametresRH.get().quota_conges_defaut


def test_route_import_salaries_requiert_permission_rh(client, login_seller):
    # login_seller n'a que "point_de_vente" et "caisse", pas "rh".
    response = client.get("/rh/import")
    assert response.status_code == 403


def test_route_import_salaries_page_accessible_admin(client, login_admin):
    response = client.get("/rh/import")
    assert response.status_code == 200
    assert b"Importer" in response.data


def test_route_import_salaries_upload_cree_le_salarie(client, login_admin, app):
    from app.models import Salarie

    fichier = _workbook_bytes(
        [
            ["Rabe Andry", "", "", "", "", "", "", "", "", ""],
        ]
    )
    response = client.post(
        "/rh/import",
        data={"fichier": (fichier, "salaries.xlsx")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200

    with app.app_context():
        assert Salarie.query.filter_by(nom="Rabe Andry").count() == 1


def test_route_modele_salaries_telecharge_un_xlsx(client, login_admin):
    response = client.get("/rh/import/modele")
    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
