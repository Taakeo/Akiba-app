import io

from openpyxl import Workbook


def _workbook_bytes(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(
        [
            "Nom du produit",
            "Poste",
            "Catégorie",
            "Sous-catégorie",
            "Fournisseur principal",
            "Unité",
            "Prix d'achat",
            "Prix de référence",
            "Stock actuel",
            "Seuil d'alerte",
            "Code-barres",
        ]
    )
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def test_importer_produits_cree_les_lignes_valides(app, db, catalogue):
    from app.admin.import_excel import importer_produits_excel
    from app.models import Produit

    fichier = _workbook_bytes(
        [
            ["Sirop de litchi", "Boutique", "Boutique", "", "", "L", 1500, 3000, 20, 5, ""],
        ]
    )

    with app.app_context():
        resultat = importer_produits_excel(fichier)

        assert resultat["crees"] == [(2, "Sirop de litchi")]
        assert resultat["ignores"] == []
        assert resultat["erreurs"] == []

        produit = Produit.query.filter_by(name="Sirop de litchi").first()
        assert produit is not None
        assert produit.prix_reference == 3000
        assert produit.stock_quantite == 20


def test_importer_produits_ignore_les_doublons(app, db, catalogue):
    from app.admin.import_excel import importer_produits_excel
    from app.models import Produit

    fichier = _workbook_bytes(
        [
            ["Tablette Chocolat 70%", "Boutique", "Boutique", "", "", "unité", "", "", 5, "", ""],
        ]
    )

    with app.app_context():
        resultat = importer_produits_excel(fichier)

        assert resultat["crees"] == []
        assert len(resultat["ignores"]) == 1
        assert Produit.query.filter_by(name="Tablette Chocolat 70%").count() == 1


def test_importer_produits_signale_un_poste_inconnu(app, db, catalogue):
    from app.admin.import_excel import importer_produits_excel

    fichier = _workbook_bytes(
        [
            ["Nouveau produit", "Poste Inexistant", "Boutique", "", "", "unité", "", "", "", "", ""],
        ]
    )

    with app.app_context():
        resultat = importer_produits_excel(fichier)

        assert resultat["crees"] == []
        assert len(resultat["erreurs"]) == 1
        assert "Poste Inexistant" in resultat["erreurs"][0][1]


def test_importer_produits_signale_un_nombre_invalide(app, db, catalogue):
    from app.admin.import_excel import importer_produits_excel

    fichier = _workbook_bytes(
        [
            ["Nouveau produit", "Boutique", "Boutique", "", "", "unité", "pas un nombre", "", "", "", ""],
        ]
    )

    with app.app_context():
        resultat = importer_produits_excel(fichier)

        assert resultat["crees"] == []
        assert len(resultat["erreurs"]) == 1
        assert "Prix d'achat" in resultat["erreurs"][0][1]


def test_importer_produits_ignore_les_lignes_vides(app, db, catalogue):
    from app.admin.import_excel import importer_produits_excel

    fichier = _workbook_bytes(
        [
            [None, None, None, None, None, None, None, None, None, None, None],
            ["Sirop de litchi", "Boutique", "Boutique", "", "", "L", "", "", "", "", ""],
        ]
    )

    with app.app_context():
        resultat = importer_produits_excel(fichier)

        assert resultat["crees"] == [(3, "Sirop de litchi")]
        assert resultat["erreurs"] == []


def test_route_import_requiert_permission_admin(client, login_seller, catalogue):
    response = client.get("/admin/produits/import")
    assert response.status_code == 403


def test_route_import_page_accessible_admin(client, login_admin, catalogue):
    response = client.get("/admin/produits/import")
    assert response.status_code == 200
    assert b"Importer" in response.data


def test_route_upload_cree_le_produit(client, login_admin, catalogue, app):
    from app.models import Produit

    fichier = _workbook_bytes(
        [
            ["Sirop de litchi", "Boutique", "Boutique", "", "", "L", "", "", "", "", ""],
        ]
    )
    response = client.post(
        "/admin/produits/import",
        data={"fichier": (fichier, "produits.xlsx")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200

    with app.app_context():
        assert Produit.query.filter_by(name="Sirop de litchi").count() == 1


def test_route_modele_telecharge_un_xlsx(client, login_admin):
    response = client.get("/admin/produits/import/modele")
    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
