"""Tests des parties de desktop.py testables sans fenêtre native ni tâche
planifiée réelle (le lancement de la fenêtre pywebview et l'installation
véritable de la tâche Windows sont validés manuellement — voir README, pas
pilotables depuis pytest)."""

import sys

import pytest


def test_commande_executable_actuel_en_dev_rappelle_python_et_le_script():
    import desktop

    commande = desktop._commande_executable_actuel()
    assert sys.executable in commande
    assert "desktop.py" in commande


def test_commande_executable_actuel_frozen_rappelle_seulement_lexe(monkeypatch):
    import desktop

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    try:
        commande = desktop._commande_executable_actuel()
        assert commande == f'"{sys.executable}"'
    finally:
        monkeypatch.delattr(sys, "frozen", raising=False)


def test_installer_tache_planifiee_ne_recree_pas_si_deja_presente(monkeypatch):
    import desktop

    appels = []
    monkeypatch.setattr(desktop, "_tache_planifiee_existe", lambda: True)
    monkeypatch.setattr(desktop.subprocess, "run", lambda *a, **k: appels.append(a))

    desktop._installer_tache_planifiee()
    assert appels == []  # aucune tentative de création : la tâche existe déjà


def test_installer_tache_planifiee_cree_si_absente(monkeypatch):
    import desktop

    appels = []
    monkeypatch.setattr(desktop, "_tache_planifiee_existe", lambda: False)
    monkeypatch.setattr(desktop.subprocess, "run", lambda *a, **k: appels.append(a))

    desktop._installer_tache_planifiee()
    assert len(appels) == 1
    commande = appels[0][0]
    assert commande[:4] == ["schtasks", "/Create", "/TN", desktop.NOM_TACHE_PLANIFIEE]
    assert "--sauvegarde" in " ".join(commande)


def test_installer_tache_planifiee_echec_reste_silencieux(monkeypatch):
    """La création de la tâche planifiée ne doit jamais empêcher le
    lancement normal de l'application (droits Windows insuffisants,
    environnement inhabituel...) — la sauvegarde manuelle reste disponible."""
    import desktop

    monkeypatch.setattr(desktop, "_tache_planifiee_existe", lambda: False)

    def _echoue(*a, **k):
        raise OSError("schtasks introuvable")

    monkeypatch.setattr(desktop.subprocess, "run", _echoue)

    desktop._installer_tache_planifiee()  # ne doit lever aucune exception


def test_executer_sauvegarde_silencieuse_journalise_le_succes(tmp_path, monkeypatch):
    import desktop
    from config import Config

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
        ENV_FILE_PATH = tmp_path / ".env"  # inexistant : simplement ignoré

    # Capturée AVANT le monkeypatch : `fake_create_app` ne doit surtout pas
    # relire "app.create_app" en interne une fois patché, sous peine de
    # s'auto-référencer (TypeError "takes 0 positional arguments but 1 was
    # given" — piégé en écrivant ce test).
    from app import create_app as reelle_create_app

    def fake_create_app():
        return reelle_create_app(TmpConfig)

    monkeypatch.setattr("app.create_app", fake_create_app)
    monkeypatch.setattr(desktop.Config, "BACKUP_DIR", tmp_path / "sauvegardes")

    code = desktop._executer_sauvegarde_silencieuse()
    assert code == 0

    journal = (tmp_path / "sauvegardes" / "journal_sauvegarde_auto.log").read_text(encoding="utf-8")
    assert "Sauvegarde automatique créée" in journal

    sauvegardes = list((tmp_path / "sauvegardes").iterdir())
    dossiers_horodates = [d for d in sauvegardes if d.is_dir()]
    assert len(dossiers_horodates) == 1
    assert (dossiers_horodates[0] / "akiba.sqlite").exists()


def test_executer_sauvegarde_silencieuse_journalise_lechec(tmp_path, monkeypatch):
    import desktop

    def fake_create_app():
        raise RuntimeError("panne simulée")

    monkeypatch.setattr("app.create_app", fake_create_app)
    monkeypatch.setattr(desktop.Config, "BACKUP_DIR", tmp_path / "sauvegardes")

    code = desktop._executer_sauvegarde_silencieuse()
    assert code == 1

    journal = (tmp_path / "sauvegardes" / "journal_sauvegarde_auto.log").read_text(encoding="utf-8")
    assert "ÉCHEC de la sauvegarde automatique" in journal
