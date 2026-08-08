import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class BackupError(Exception):
    pass


def log_audit(app, action, detail, current_user):
    """Journal d'audit en fichier plat, volontairement séparé de la base de
    données : le CDC (§13.1) exige que la création du log de restauration
    précède l'écrasement effectif de la base — un log stocké *dans* la base
    serait perdu au moment même où il devrait faire foi."""
    entry = {
        "horodatage": utcnow().isoformat(),
        "action": action,
        "detail": detail,
        "utilisateur": current_user.full_name if current_user else "système",
    }
    path = Path(app.config["AUDIT_LOG_PATH"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _chemin_config_sauvegarde(app):
    return Path(app.config["INSTANCE_DIR"]) / "backup_config.json"


def lire_destination_sauvegarde(app):
    """Chemin du dossier de sauvegarde configuré (ex. un disque externe),
    ou None si le réglage par défaut (instance/sauvegardes/) est utilisé.
    Stocké en fichier plat volontairement séparé de la base — le même
    raisonnement que pour le journal d'audit : ce réglage doit rester lisible
    même quand la base est en cours de sauvegarde/restauration."""
    path = _chemin_config_sauvegarde(app)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data.get("dossier_destination") or None


def ecrire_destination_sauvegarde(app, dossier):
    """Enregistre le dossier de destination (chaîne vide = revenir au
    réglage par défaut). Ne vérifie que l'écrivabilité, jamais l'espace
    disque disponible (impossible à garantir à l'avance de toute façon)."""
    dossier = (dossier or "").strip()
    if dossier:
        cible = Path(dossier)
        try:
            cible.mkdir(parents=True, exist_ok=True)
            test_file = cible / ".akiba_test_ecriture"
            test_file.write_text("test", encoding="utf-8")
            test_file.unlink()
        except (OSError, ValueError) as exc:
            raise BackupError(f"Dossier inutilisable ({exc}). Vérifiez qu'il existe et est accessible en écriture.")

    path = _chemin_config_sauvegarde(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"dossier_destination": dossier}, ensure_ascii=False), encoding="utf-8")


def dossier_sauvegardes_actuel(app):
    """Dossier réellement utilisé pour les sauvegardes : celui configuré
    s'il est toujours valide, sinon le dossier par défaut (jamais d'erreur
    silencieuse — un disque externe débranché ne doit pas faire disparaître
    les sauvegardes déjà faites en local)."""
    configure = lire_destination_sauvegarde(app)
    if configure:
        chemin = Path(configure)
        if chemin.exists() and chemin.is_dir():
            return chemin
    return Path(app.config["BACKUP_DIR"])


def espace_disque_disponible(dossier):
    """(octets libres, octets totaux) sur le disque contenant ce dossier, ou
    None si l'information n'est pas disponible (dossier inexistant...)."""
    try:
        usage = shutil.disk_usage(dossier)
        return usage.free, usage.total
    except OSError:
        return None


def lire_audit_log(app, limite=50):
    path = Path(app.config["AUDIT_LOG_PATH"])
    if not path.exists():
        return []
    lignes = path.read_text(encoding="utf-8").splitlines()
    entrees = [json.loads(ligne) for ligne in lignes if ligne.strip()]
    return list(reversed(entrees))[:limite]


def _dossier_taille(dossier):
    return sum(f.stat().st_size for f in Path(dossier).rglob("*") if f.is_file())


def lister_sauvegardes(app):
    backup_dir = dossier_sauvegardes_actuel(app)
    if not backup_dir.exists():
        return []

    items = []
    for dossier in sorted(backup_dir.iterdir(), reverse=True):
        if not dossier.is_dir():
            continue
        db_file = dossier / Path(app.config["DATABASE_PATH"]).name
        try:
            horodatage = datetime.strptime(dossier.name, "%Y%m%d_%H%M%S")
            date_affichee = horodatage.strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            date_affichee = dossier.name
        items.append(
            {
                "nom": dossier.name,
                "date_affichee": date_affichee,
                "complet": db_file.exists(),
                "taille_octets": _dossier_taille(dossier),
            }
        )
    return items


def creer_sauvegarde(app, current_user):
    """Copie horodatée de la base chiffrée + des pièces jointes. Purge les
    sauvegardes au-delà de BACKUP_KEEP_COUNT. §13.1 spec."""
    horodatage = utcnow().strftime("%Y%m%d_%H%M%S")
    backup_dir = dossier_sauvegardes_actuel(app) / horodatage
    backup_dir.mkdir(parents=True, exist_ok=True)

    db_path = Path(app.config["DATABASE_PATH"])
    if not db_path.exists():
        raise BackupError("Aucune base de données à sauvegarder.")

    # On s'assure qu'aucune transaction n'est en cours et on libère la
    # connexion avant la copie, pour ne pas copier un fichier en cours d'écriture.
    db.session.commit()
    db.engine.dispose()

    shutil.copy2(db_path, backup_dir / db_path.name)

    uploads_root = Path(app.config["UPLOADS_ROOT"])
    if uploads_root.exists():
        shutil.copytree(uploads_root, backup_dir / "uploads", dirs_exist_ok=True)

    _purger_anciennes_sauvegardes(app)
    log_audit(app, "sauvegarde_creee", horodatage, current_user)

    return horodatage


def _purger_anciennes_sauvegardes(app):
    backup_dir = dossier_sauvegardes_actuel(app)
    keep = app.config["BACKUP_KEEP_COUNT"]
    dossiers = sorted((d for d in backup_dir.iterdir() if d.is_dir()), reverse=True)
    for dossier in dossiers[keep:]:
        shutil.rmtree(dossier, ignore_errors=True)


def restaurer_sauvegarde(app, nom, current_user):
    """Écrasement direct (pas de fusion) de la base et des pièces jointes par
    la sauvegarde choisie. Le journal d'audit est écrit AVANT l'écrasement,
    car après le remplacement du fichier la transaction courante n'a plus de
    sens pour logger après coup. §13.1 spec."""
    backup_dir = dossier_sauvegardes_actuel(app) / nom
    db_path = Path(app.config["DATABASE_PATH"])
    backup_db_file = backup_dir / db_path.name

    if not backup_db_file.exists():
        raise BackupError(f"Sauvegarde introuvable ou incomplète : {nom}")

    log_audit(app, "sauvegarde_restauree", nom, current_user)

    db.session.commit()
    db.engine.dispose()

    shutil.copy2(backup_db_file, db_path)

    backup_uploads = backup_dir / "uploads"
    uploads_root = Path(app.config["UPLOADS_ROOT"])
    if backup_uploads.exists():
        if uploads_root.exists():
            shutil.rmtree(uploads_root)
        shutil.copytree(backup_uploads, uploads_root)
