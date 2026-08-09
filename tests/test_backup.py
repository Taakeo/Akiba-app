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


def test_creer_sauvegarde_inclut_env_et_cles(tmp_path):
    """Sans le `.env`/les clés persistées, une base chiffrée copiée dans une
    sauvegarde est illisible pour toujours en cas de restauration sur un
    nouveau poste — même piège déjà rencontré et corrigé sur le projet
    École Akiba (07/08/2026)."""
    from app import create_app
    from app.admin.backup_service import creer_sauvegarde

    env_path = tmp_path / ".env"
    env_path.write_text("FLASK_SECRET_KEY=abc\nDB_ENCRYPTION_KEY=def\n", encoding="utf-8")

    config_cls = _make_config(tmp_path)
    config_cls.ENV_FILE_PATH = env_path
    app = create_app(config_cls)

    # Simule les clés auto-générées et persistées dans INSTANCE_DIR (cas
    # sans .env explicite — voir config.py::_cle_persistante).
    (tmp_path / ".flask_secret_key").write_text("cle-secrete", encoding="utf-8")
    (tmp_path / ".db_encryption_key").write_text("cle-chiffrement", encoding="utf-8")

    with app.app_context():
        nom = creer_sauvegarde(app, FakeUser())

    backup_dir = tmp_path / "sauvegardes" / nom
    assert (backup_dir / ".env").read_text(encoding="utf-8") == env_path.read_text(encoding="utf-8")
    assert (backup_dir / ".flask_secret_key").read_text(encoding="utf-8") == "cle-secrete"
    assert (backup_dir / ".db_encryption_key").read_text(encoding="utf-8") == "cle-chiffrement"


def test_restaurer_sauvegarde_restaure_env_et_cles(tmp_path):
    from app import create_app
    from app.admin.backup_service import creer_sauvegarde, restaurer_sauvegarde

    env_path = tmp_path / ".env"
    env_path.write_text("FLASK_SECRET_KEY=original\n", encoding="utf-8")

    config_cls = _make_config(tmp_path)
    config_cls.ENV_FILE_PATH = env_path
    app = create_app(config_cls)

    with app.app_context():
        nom = creer_sauvegarde(app, FakeUser())

    # Le .env "courant" change après la sauvegarde (scénario : disque
    # remplacé, .env différent en place) — la restauration doit le remettre
    # cohérent avec la base qu'il déchiffre.
    env_path.write_text("FLASK_SECRET_KEY=modifie\n", encoding="utf-8")

    with app.app_context():
        restaurer_sauvegarde(app, nom, FakeUser())

    assert env_path.read_text(encoding="utf-8") == "FLASK_SECRET_KEY=original\n"


def test_lister_lecteurs_disponibles(monkeypatch):
    from pathlib import Path

    from app.admin.backup_service import lister_lecteurs_disponibles

    def fake_exists(self):
        return str(self) in ("D:\\", "E:\\")

    def fake_disk_usage(chemin):
        return (100 * 1024**3, 40 * 1024**3, 60 * 1024**3) if str(chemin) == "D:\\" else (100 * 1024**3, 90 * 1024**3, 10 * 1024**3)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr("shutil.disk_usage", fake_disk_usage)

    lecteurs = lister_lecteurs_disponibles()
    assert [l["lettre"] for l in lecteurs] == ["D", "E"]
    assert lecteurs[0]["libre_go"] == 60
    assert lecteurs[1]["libre_go"] == 10


def test_creer_sauvegarde_externe(tmp_path, monkeypatch):
    from pathlib import Path as RealPath

    from app import create_app
    from app.admin import backup_service
    from app.admin.backup_service import NOM_DOSSIER_SAUVEGARDES_EXTERNES, creer_sauvegarde_externe

    disque = tmp_path / "disque_D"
    disque.mkdir()

    # Redirige "D:/" vers un vrai dossier temporaire, sans dépendre d'un
    # vrai lecteur D: sur la machine qui exécute les tests.
    monkeypatch.setattr(
        backup_service, "Path", lambda p="": RealPath(str(p).replace("D:/", str(disque) + "/"))
    )

    app = create_app(_make_config(tmp_path))
    with app.app_context():
        nom = creer_sauvegarde_externe(app, FakeUser(), "D")

    cible = disque / NOM_DOSSIER_SAUVEGARDES_EXTERNES / nom
    assert (cible / "akiba.sqlite").exists()


def test_route_sauvegarde_externe_refuse_lecteur_absent(client, login_admin, catalogue, monkeypatch):
    from app.admin import routes_backup

    monkeypatch.setattr(routes_backup, "lister_lecteurs_disponibles", lambda: [])

    response = client.post("/admin/sauvegardes/nouvelle-externe/Z", follow_redirects=True)
    assert response.status_code == 200
    assert "plus disponible".encode() in response.data
