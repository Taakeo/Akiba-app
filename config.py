import os
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv


def _dossier_ressources():
    """Dossier où se trouvent les ressources embarquées (templates, static,
    polices...). En exécutable PyInstaller (--onefile), c'est le dossier
    d'extraction temporaire (`sys._MEIPASS`) ; en développement, c'est
    simplement la racine du projet."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def _dossier_donnees_utilisateur():
    """Dossier où la base de données et les fichiers utilisateur sont
    écrits. Jamais dans le dossier d'installation/extraction : celui d'un
    .exe PyInstaller est souvent en lecture seule (Program Files) ou
    carrément éphémère (dossier temporaire recréé à chaque lancement en
    mode --onefile) — écrire là perdrait les données au redémarrage suivant.
    En exécutable, on utilise donc %LOCALAPPDATA%\\AKIBA APP (profil
    utilisateur Windows, toujours accessible en écriture sans droits
    administrateur, stable d'un lancement à l'autre et d'une mise à jour à
    l'autre de l'application). En développement, on garde `instance/` à la
    racine du projet comme avant, pour rester visible et versionnable dans
    .gitignore sans changer les habitudes de dev."""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AKIBA APP"
        base.mkdir(parents=True, exist_ok=True)
        return base
    return Path(__file__).resolve().parent / "instance"


BASE_DIR = _dossier_ressources()
INSTANCE_DIR = _dossier_donnees_utilisateur()

# En dev, .env reste à la racine du projet (workflow existant, non versionné).
# En exécutable, un .env n'a normalement pas lieu d'exister (rien à éditer à
# la main pour l'utilisateur final) : s'il en dépose un manuellement à côté
# de l'exécutable, il est quand même pris en compte (permet de forcer une
# config avancée sans recompiler).
if getattr(sys, "frozen", False):
    load_dotenv(Path(sys.executable).resolve().parent / ".env")
else:
    load_dotenv(BASE_DIR / ".env")


def _cle_persistante(nom_fichier, variable_env):
    """Secret auto-généré et persisté au premier lancement plutôt qu'exigé
    de l'utilisateur final : personne chez Akiba ne doit avoir à éditer un
    fichier .env pour que l'application soit sûre par défaut. La variable
    d'environnement reste prioritaire quand elle est explicitement définie
    (workflow de dev existant, ou configuration avancée volontaire)."""
    valeur_env = os.environ.get(variable_env)
    if valeur_env:
        return valeur_env

    chemin = INSTANCE_DIR / nom_fichier
    if chemin.exists():
        valeur = chemin.read_text(encoding="utf-8").strip()
        if valeur:
            return valeur

    valeur = secrets.token_hex(32)
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    chemin.write_text(valeur, encoding="utf-8")
    return valeur


class Config:
    SECRET_KEY = _cle_persistante(".flask_secret_key", "FLASK_SECRET_KEY")
    DB_ENCRYPTION_KEY = _cle_persistante(".db_encryption_key", "DB_ENCRYPTION_KEY")

    INSTANCE_DIR = INSTANCE_DIR
    DATABASE_PATH = INSTANCE_DIR / "akiba.sqlite"

    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATABASE_PATH}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    WTF_CSRF_ENABLED = True

    # Suspension prolongée d'un sous-profil -> suppression (§3 spec)
    SUBPROFILE_SUSPENSION_PURGE_DAYS = int(
        os.environ.get("SUBPROFILE_SUSPENSION_PURGE_DAYS", "90")
    )

    BACKUP_DIR = INSTANCE_DIR / "sauvegardes"
    BACKUP_KEEP_COUNT = 10

    # Déconnexion automatique par inactivité (§1.5/§3 CDC) — filet de sécurité
    # sur un poste partagé à PIN, en complément du choix explicite proposé au
    # vendeur après chaque vente ("vente suivante ?" / "terminer ma session").
    INACTIVITY_TIMEOUT_MINUTES = int(os.environ.get("INACTIVITY_TIMEOUT_MINUTES", "5"))

    # Pièces jointes (factures, devis, photos, BL) — pas de BLOB en base (§13.1)
    UPLOADS_ROOT = INSTANCE_DIR / "uploads"
    UPLOAD_DIR = UPLOADS_ROOT / "achats"
    UPLOAD_DIR_PRODUITS = UPLOADS_ROOT / "produits"
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 Mo par requête

    AUDIT_LOG_PATH = INSTANCE_DIR / "audit.log"


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    DB_ENCRYPTION_KEY = None  # pas de chiffrement pour la base de test en mémoire
