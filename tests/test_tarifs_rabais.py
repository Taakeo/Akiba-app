def test_activer_rabais_tarif(client, login_admin, db):
    from app.models import TypeTarif

    client.post("/admin/tarifs", data={"label": "Adhérent"})
    adherent = TypeTarif.query.filter_by(label="Adhérent").first()

    response = client.post(
        f"/admin/tarifs/{adherent.id}/rabais",
        data={"pourcentage_rabais": "10", "rabais_actif": "y"},
    )
    assert response.status_code == 302

    db.session.refresh(adherent)
    assert adherent.pourcentage_rabais == 10
    assert adherent.rabais_actif is True


def test_activer_rabais_sans_pourcentage_refuse(client, login_admin, db):
    from app.models import TypeTarif

    client.post("/admin/tarifs", data={"label": "Adhérent"})
    adherent = TypeTarif.query.filter_by(label="Adhérent").first()

    client.post(f"/admin/tarifs/{adherent.id}/rabais", data={"rabais_actif": "y"})

    db.session.refresh(adherent)
    assert adherent.rabais_actif is False


def test_desactiver_rabais_conserve_le_pourcentage(client, login_admin, db):
    from app.models import TypeTarif

    client.post("/admin/tarifs", data={"label": "Adhérent"})
    adherent = TypeTarif.query.filter_by(label="Adhérent").first()
    client.post(
        f"/admin/tarifs/{adherent.id}/rabais",
        data={"pourcentage_rabais": "10", "rabais_actif": "y"},
    )

    # Re-soumission sans la case cochée : décoche le rabais mais garde le %.
    client.post(f"/admin/tarifs/{adherent.id}/rabais", data={"pourcentage_rabais": "10"})

    db.session.refresh(adherent)
    assert adherent.rabais_actif is False
    assert adherent.pourcentage_rabais == 10


def _setup_produit(db, prix_reference=None, rabais_actif=True):
    from app.models import Categorie, Poste, Produit, TypeTarif

    poste = Poste(name="Boutique")
    db.session.add(poste)
    db.session.flush()
    categorie = Categorie(poste_id=poste.id, name="Boutique")
    db.session.add(categorie)
    db.session.flush()

    tarif_adherent = TypeTarif(
        code="adherent", label="Adhérent", ordre=2, pourcentage_rabais=10, rabais_actif=rabais_actif
    )
    db.session.add(tarif_adherent)

    produit = Produit(
        name="Miel d'Akiba",
        categorie_id=categorie.id,
        poste_id=poste.id,
        stock_quantite=5,
        prix_reference=prix_reference,
    )
    db.session.add(produit)
    db.session.commit()
    return produit, tarif_adherent


def test_prix_pour_calcule_avec_rabais_arrondi_a_la_centaine_superieure(app, db):
    produit, _ = _setup_produit(db, prix_reference=5050)
    # 5050 - 10% = 4545, arrondi à la centaine supérieure = 4600.
    assert produit.prix_pour("adherent") == 4600


def test_prix_manuel_prime_sur_le_rabais_automatique(app, db):
    from app.models import PrixProduit

    produit, tarif_adherent = _setup_produit(db, prix_reference=5000)
    db.session.add(PrixProduit(produit_id=produit.id, type_tarif_id=tarif_adherent.id, montant=4000))
    db.session.commit()

    assert produit.prix_pour("adherent") == 4000  # pas 4500 (5000 - 10%)


def test_prix_indisponible_sans_prix_reference_ni_prix_manuel(app, db):
    produit, _ = _setup_produit(db, prix_reference=None)
    assert produit.prix_pour("adherent") is None


def test_rabais_inactif_ne_calcule_rien(app, db):
    produit, _ = _setup_produit(db, prix_reference=5000, rabais_actif=False)
    assert produit.prix_pour("adherent") is None
