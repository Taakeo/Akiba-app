from datetime import date

import pytest

from config import Config


class FakeUser:
    id = None
    full_name = "Testeur"


def _make_config(tmp_path):
    class TmpConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        DB_ENCRYPTION_KEY = None
        INSTANCE_DIR = tmp_path
        DATABASE_PATH = tmp_path / "akiba.sqlite"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'akiba.sqlite'}"
        BACKUP_DIR = tmp_path / "sauvegardes"
        UPLOADS_ROOT = tmp_path / "uploads"
        UPLOAD_DIR = tmp_path / "uploads" / "achats"
        AUDIT_LOG_PATH = tmp_path / "audit.log"
        BACKUP_KEEP_COUNT = 10

    return TmpConfig


@pytest.fixture
def file_app(tmp_path):
    from app import create_app

    return create_app(_make_config(tmp_path))


def _construire_donnees_de_test(db):
    """Un petit jeu de données réaliste couvrant toutes les tables purgées
    par reinitialiser_pour_production() + du catalogue/comptes à conserver."""
    from app.models import (
        Achat,
        CaisseSession,
        Categorie,
        Client,
        CompteFinancier,
        LigneVente,
        MoyenPaiement,
        Poste,
        PrixProduit,
        Produit,
        TypeTarif,
        Vente,
        VentePaiement,
    )

    poste = Poste(name="Boutique")
    db.session.add(poste)
    db.session.flush()

    categorie = Categorie(poste_id=poste.id, name="Boutique")
    db.session.add(categorie)
    db.session.flush()

    produit = Produit(name="Tablette", categorie_id=categorie.id, poste_id=poste.id, stock_quantite=7, seuil_alerte=2)
    db.session.add(produit)
    db.session.flush()

    tarif = TypeTarif(code="standard", label="Standard", ordre=1, is_default=True)
    db.session.add(tarif)
    db.session.flush()
    db.session.add(PrixProduit(produit_id=produit.id, type_tarif_id=tarif.id, montant=8000))

    compte = CompteFinancier(name="Caisse Ariary", devise="Ar", is_caisse_physique=True)
    db.session.add(compte)
    db.session.flush()
    moyen = MoyenPaiement(name="Espèces Ariary", compte_financier_id=compte.id)
    db.session.add(moyen)
    db.session.flush()

    client = Client(nom="Rakoto", solde_credit=5000)
    db.session.add(client)
    db.session.flush()

    session = CaisseSession(compte_financier_id=compte.id, statut="ouverte", fond_ouverture=0, ouverte_par_nom="Test")
    db.session.add(session)
    db.session.flush()

    vente = Vente(
        caisse_session_id=session.id,
        type_tarif_id=tarif.id,
        client_id=client.id,
        sous_total=8000,
        total=8000,
        created_by_name="Test",
    )
    db.session.add(vente)
    db.session.flush()
    db.session.add(
        LigneVente(
            vente_id=vente.id,
            produit_id=produit.id,
            produit_nom=produit.name,
            poste_id=poste.id,
            categorie_id=categorie.id,
            quantite=1,
            prix_unitaire=8000,
            total_ligne=8000,
        )
    )
    db.session.add(VentePaiement(vente_id=vente.id, moyen_paiement_id=moyen.id, montant=8000))
    compte.solde = 8000

    achat = Achat(
        type_achat="depense",
        date_achat=date.today(),
        poste_id=poste.id,
        categorie_id=categorie.id,
        montant_total=1000,
        moyen_paiement_id=moyen.id,
        created_by_name="Test",
    )
    db.session.add(achat)

    db.session.commit()
    return {
        "produit_id": produit.id,
        "compte_id": compte.id,
        "client_id": client.id,
        "vente_id": vente.id,
    }


def test_reinitialisation_requiert_permission_admin(client, login_seller):
    assert client.get("/admin/reinitialisation").status_code == 403
    assert client.post("/admin/reinitialisation", data={"confirmation": "RÉINITIALISER"}).status_code == 403


def test_reinitialisation_refuse_sans_la_phrase_exacte(client, login_admin):
    response = client.post("/admin/reinitialisation", data={"confirmation": "oui"})
    assert response.status_code == 200  # ré-affiche le formulaire, pas de redirection
    assert "Tapez exactement".encode() in response.data


def test_reinitialisation_vide_lhistorique_et_garde_le_catalogue_stock_prix(file_app):
    from app.admin.reset_service import reinitialiser_pour_production
    from app.extensions import db
    from app.models import (
        Achat,
        CaisseSession,
        Client,
        CompteFinancier,
        MouvementStock,
        PrixProduit,
        Produit,
        Vente,
    )

    with file_app.app_context():
        donnees = _construire_donnees_de_test(db)

        reinitialiser_pour_production(file_app, FakeUser())

        assert Vente.query.count() == 0
        assert Achat.query.count() == 0
        assert CaisseSession.query.count() == 0

        compte = db.session.get(CompteFinancier, donnees["compte_id"])
        assert compte.solde == 0

        client_obj = db.session.get(Client, donnees["client_id"])
        assert client_obj.solde_credit == 0

        # Conservé tel quel : stock, prix, catalogue.
        produit = db.session.get(Produit, donnees["produit_id"])
        assert produit.stock_quantite == 7
        assert PrixProduit.query.filter_by(produit_id=produit.id).first().montant == 8000

        # Le stock restant a bien un mouvement de départ pour rester
        # cohérent (jamais un stock non nul sans aucun historique).
        mouvements = MouvementStock.query.filter_by(produit_id=produit.id).all()
        assert len(mouvements) == 1
        assert mouvements[0].quantite == 7
        assert mouvements[0].motif == "correction"
        assert mouvements[0].type_mouvement == "entree"
        assert produit.stock_quantite == 7  # bien inchangé par ce mouvement de journalisation


def test_reinitialisation_cree_une_sauvegarde_avant_de_purger(file_app):
    from app.admin.backup_service import lister_sauvegardes
    from app.admin.reset_service import reinitialiser_pour_production
    from app.extensions import db

    with file_app.app_context():
        _construire_donnees_de_test(db)
        reinitialiser_pour_production(file_app, FakeUser())
        assert len(lister_sauvegardes(file_app)) == 1


def test_reinitialisation_echoue_et_narrete_rien_si_la_sauvegarde_echoue(file_app, monkeypatch):
    from app.admin.backup_service import BackupError
    from app.admin.reset_service import ReinitialisationError, reinitialiser_pour_production
    from app.extensions import db
    from app.models import Vente

    with file_app.app_context():
        _construire_donnees_de_test(db)

        def _echoue(app, current_user):
            raise BackupError("disque plein")

        monkeypatch.setattr("app.admin.reset_service.creer_sauvegarde", _echoue)

        with pytest.raises(ReinitialisationError):
            reinitialiser_pour_production(file_app, FakeUser())

        # Rien n'a été effacé.
        assert Vente.query.count() == 1


def test_reinitialisation_bout_en_bout_via_la_route(file_app):
    from app.extensions import db
    from app.models import Profile, SubProfile, Vente

    with file_app.app_context():
        _construire_donnees_de_test(db)

        profile = Profile(code="administrateur", name="Administrateur", icon="shield_person")
        profile.permissions = ["*"]
        db.session.add(profile)
        db.session.commit()
        sub = SubProfile(profile_id=profile.id, full_name="Admin")
        sub.set_pin("9999")
        db.session.add(sub)
        db.session.commit()
        profile_id, sub_id = profile.id, sub.id

    test_client = file_app.test_client()
    test_client.post(f"/auth/profil/{profile_id}/utilisateur/{sub_id}", data={"pin": "9999"})

    response = test_client.post("/admin/reinitialisation", data={"confirmation": "RÉINITIALISER"})
    assert response.status_code == 302

    with file_app.app_context():
        assert Vente.query.count() == 0
