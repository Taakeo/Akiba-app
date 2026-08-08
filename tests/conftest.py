import pytest

from app import create_app
from app.extensions import db as _db
from app.models import Profile, SubProfile
from config import TestConfig


@pytest.fixture
def app():
    application = create_app(TestConfig)
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    with app.app_context():
        yield _db


@pytest.fixture
def seller_profile(app, db):
    with app.app_context():
        profile = Profile(code="vendeur", name="Vendeur", icon="point_of_sale")
        profile.permissions = ["point_de_vente", "caisse"]
        db.session.add(profile)
        db.session.commit()
        return profile.id


@pytest.fixture
def seller_subprofile(app, db, seller_profile):
    with app.app_context():
        sub_profile = SubProfile(profile_id=seller_profile, full_name="Sarah")
        sub_profile.set_pin("1234")
        db.session.add(sub_profile)
        db.session.commit()
        return sub_profile.id


@pytest.fixture
def login_seller(client, seller_profile, seller_subprofile):
    client.post(
        f"/auth/profil/{seller_profile}/utilisateur/{seller_subprofile}",
        data={"pin": "1234"},
    )
    return seller_subprofile


@pytest.fixture
def admin_profile(app, db):
    with app.app_context():
        profile = Profile(code="administrateur", name="Administrateur", icon="shield_person")
        profile.permissions = ["*"]
        db.session.add(profile)
        db.session.commit()
        return profile.id


@pytest.fixture
def admin_subprofile(app, db, admin_profile):
    with app.app_context():
        sub_profile = SubProfile(profile_id=admin_profile, full_name="Admin")
        sub_profile.set_pin("9999")
        db.session.add(sub_profile)
        db.session.commit()
        return sub_profile.id


@pytest.fixture
def login_admin(client, admin_profile, admin_subprofile):
    client.post(
        f"/auth/profil/{admin_profile}/utilisateur/{admin_subprofile}",
        data={"pin": "9999"},
    )
    return admin_subprofile


@pytest.fixture
def catalogue(app, db):
    from app.models import Categorie, CompteFinancier, MoyenPaiement, Poste, PrixProduit, Produit, TypeTarif

    with app.app_context():
        caisse = CompteFinancier(name="Caisse Ariary", devise="Ar", is_caisse_physique=True)
        db.session.add(caisse)
        db.session.flush()

        moyen_especes = MoyenPaiement(name="Espèces Ariary", compte_financier_id=caisse.id, ouvre_tiroir=True)
        db.session.add(moyen_especes)

        tarif_standard = TypeTarif(code="standard", label="Standard", ordre=1, is_default=True)
        db.session.add(tarif_standard)

        poste = Poste(name="Boutique")
        db.session.add(poste)
        db.session.flush()

        categorie = Categorie(poste_id=poste.id, name="Boutique")
        db.session.add(categorie)
        db.session.flush()

        produit = Produit(
            name="Tablette Chocolat 70%",
            categorie_id=categorie.id,
            poste_id=poste.id,
            stock_quantite=10,
            seuil_alerte=2,
        )
        db.session.add(produit)
        db.session.flush()

        db.session.add(PrixProduit(produit_id=produit.id, type_tarif_id=tarif_standard.id, montant=8000))
        db.session.commit()

        return {
            "caisse_id": caisse.id,
            "moyen_paiement_id": moyen_especes.id,
            "type_tarif_id": tarif_standard.id,
            "produit_id": produit.id,
            "poste_id": poste.id,
            "categorie_id": categorie.id,
        }
