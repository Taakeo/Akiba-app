import pytest

from config import Config


class FakeUser:
    full_name = "Testeur"


def _make_config(tmp_path, keep=10):
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
        BACKUP_KEEP_COUNT = keep

    return TmpConfig


@pytest.fixture
def file_app(tmp_path):
    from app import create_app

    application = create_app(_make_config(tmp_path))
    return application


def test_creer_sauvegarde_copie_la_base(file_app):
    from app.admin.backup_service import creer_sauvegarde, lister_sauvegardes

    with file_app.app_context():
        nom = creer_sauvegarde(file_app, FakeUser())

        backups = lister_sauvegardes(file_app)
        assert len(backups) == 1
        assert backups[0]["nom"] == nom
        assert backups[0]["complet"] is True


def test_restaurer_revient_a_l_etat_sauvegarde(file_app):
    from app.admin.backup_service import creer_sauvegarde, restaurer_sauvegarde
    from app.extensions import db
    from app.models import Poste

    with file_app.app_context():
        db.session.add(Poste(name="Boutique"))
        db.session.commit()

        nom_backup = creer_sauvegarde(file_app, FakeUser())

        db.session.add(Poste(name="Agriculture"))
        db.session.commit()
        assert Poste.query.count() == 2

        restaurer_sauvegarde(file_app, nom_backup, FakeUser())

        # après restauration, une nouvelle connexion doit refléter l'état sauvegardé
        assert Poste.query.count() == 1
        assert Poste.query.first().name == "Boutique"


def test_restaurer_sauvegarde_inexistante_leve_erreur(file_app):
    from app.admin.backup_service import BackupError, restaurer_sauvegarde

    with file_app.app_context():
        with pytest.raises(BackupError):
            restaurer_sauvegarde(file_app, "20000101_000000", FakeUser())


def test_audit_log_journalise_avant_ecrasement(file_app):
    from app.admin.backup_service import creer_sauvegarde, lire_audit_log, restaurer_sauvegarde

    with file_app.app_context():
        nom = creer_sauvegarde(file_app, FakeUser())
        restaurer_sauvegarde(file_app, nom, FakeUser())

        audit = lire_audit_log(file_app)
        assert len(audit) == 2
        assert audit[0]["action"] == "sauvegarde_restauree"  # le plus récent en premier
        assert audit[1]["action"] == "sauvegarde_creee"
        assert audit[0]["utilisateur"] == "Testeur"


def test_destination_personnalisee_utilisee_pour_les_sauvegardes(file_app, tmp_path):
    from app.admin.backup_service import (
        creer_sauvegarde,
        dossier_sauvegardes_actuel,
        ecrire_destination_sauvegarde,
        lister_sauvegardes,
    )

    disque_externe = tmp_path / "disque_externe"
    disque_externe.mkdir()

    with file_app.app_context():
        ecrire_destination_sauvegarde(file_app, str(disque_externe))
        assert dossier_sauvegardes_actuel(file_app) == disque_externe

        nom = creer_sauvegarde(file_app, FakeUser())

        # La sauvegarde a bien atterri sur le "disque externe", pas dans le
        # dossier par défaut.
        assert (disque_externe / nom / "akiba.sqlite").exists()
        assert not (file_app.config["BACKUP_DIR"] / nom).exists()

        backups = lister_sauvegardes(file_app)
        assert len(backups) == 1
        assert backups[0]["nom"] == nom


def test_destination_vide_revient_au_dossier_par_defaut(file_app, tmp_path):
    from app.admin.backup_service import (
        dossier_sauvegardes_actuel,
        ecrire_destination_sauvegarde,
        lire_destination_sauvegarde,
    )

    disque_externe = tmp_path / "disque_externe"
    disque_externe.mkdir()

    with file_app.app_context():
        ecrire_destination_sauvegarde(file_app, str(disque_externe))
        assert lire_destination_sauvegarde(file_app) == str(disque_externe)

        ecrire_destination_sauvegarde(file_app, "")
        assert lire_destination_sauvegarde(file_app) is None
        assert dossier_sauvegardes_actuel(file_app) == file_app.config["BACKUP_DIR"]


def test_destination_debranchee_retombe_sur_le_defaut(file_app, tmp_path):
    """Un disque externe débranché (dossier disparu) ne doit jamais faire
    disparaître silencieusement les sauvegardes : on retombe sur le dossier
    par défaut plutôt que de planter ou de perdre l'historique local."""
    from app.admin.backup_service import dossier_sauvegardes_actuel, ecrire_destination_sauvegarde

    disque_amovible = tmp_path / "disque_amovible"
    disque_amovible.mkdir()

    with file_app.app_context():
        ecrire_destination_sauvegarde(file_app, str(disque_amovible))

    disque_amovible.rmdir()  # simule le débranchement

    with file_app.app_context():
        assert dossier_sauvegardes_actuel(file_app) == file_app.config["BACKUP_DIR"]


def test_destination_illisible_refuse_avec_message_clair(file_app):
    from app.admin.backup_service import BackupError, ecrire_destination_sauvegarde

    with file_app.app_context():
        with pytest.raises(BackupError):
            # Un fichier NUL/chemin invalide sous Windows n'est pas un dossier créable.
            ecrire_destination_sauvegarde(file_app, "\x00invalide")


def test_purge_conserve_seulement_les_n_plus_recentes(file_app):
    from app.admin.backup_service import _purger_anciennes_sauvegardes, lister_sauvegardes

    file_app.config["BACKUP_KEEP_COUNT"] = 2
    backup_dir = file_app.config["BACKUP_DIR"]
    backup_dir.mkdir(parents=True, exist_ok=True)

    for horodatage in ["20200101_000000", "20200101_000001", "20200101_000002"]:
        dossier = backup_dir / horodatage
        dossier.mkdir()
        (dossier / "akiba.sqlite").write_text("fake")

    with file_app.app_context():
        _purger_anciennes_sauvegardes(file_app)
        restants = lister_sauvegardes(file_app)

    assert len(restants) == 2
    assert {b["nom"] for b in restants} == {"20200101_000001", "20200101_000002"}
