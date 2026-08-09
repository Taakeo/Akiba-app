"""Point d'entrée du déploiement "fenêtre native" (§2.1, §15.1 spec —
décision de déploiement tranchée par l'utilisateur : pywebview + PyInstaller,
téléchargements autorisés comme dans un navigateur).

Fait tourner l'application Flask via Waitress (serveur WSGI de production,
pas le serveur de dev Flask) sur un port local libre, puis ouvre une
fenêtre native pointant dessus — aucun navigateur externe à lancer, aucune
adresse à taper, conforme à la contrainte "100% hors ligne, poste unique"
(§2). C'est ce fichier (compilé en .exe par PyInstaller) que l'utilisateur
final double-clique.

Deux modes (même patron que École/Dispensaire Akiba, retour utilisateur du
09/08/2026) :
  - lancement normal (aucun argument) : fenêtre native + installe
    silencieusement (au tout premier lancement) une tâche planifiée Windows
    pour la sauvegarde automatique, sans aucune action du client.
  - `--sauvegarde` : exécute une sauvegarde silencieuse et quitte — c'est la
    commande que la tâche planifiée elle-même déclenche deux fois par jour
    (elle rappelle ce même exécutable, pas un script Python séparé, pour ne
    dépendre d'aucun interpréteur installé sur la machine cible)."""

import ctypes
import socket
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from config import BASE_DIR, Config

CHEMIN_ICONE = str(BASE_DIR / "app" / "static" / "vendor" / "logo" / "akiba.ico")
NOM_TACHE_PLANIFIEE = "Sauvegarde AKIBA APP"


class _UtilisateurSysteme:
    """Auteur affiché sur les sauvegardes créées automatiquement par la
    tâche planifiée — même principe que la purge automatique des
    utilisateurs suspendus (app/cli.py::_UtilisateurSysteme)."""

    full_name = "Système (sauvegarde automatique)"


def _port_libre():
    """Port local libre choisi dynamiquement — évite un conflit si un autre
    programme occupe déjà un port fixe, et évite d'exposer le service sur
    le réseau (bind 127.0.0.1 uniquement, jamais 0.0.0.0)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _demarrer_serveur(app, port):
    from waitress import serve

    serve(app, host="127.0.0.1", port=port, threads=8)


def _afficher_pin_premier_demarrage(pin):
    """Boîte de dialogue Windows native (sans dépendance supplémentaire,
    juste ctypes/user32) affichée AVANT la fenêtre principale, pour que le
    tout premier PIN administrateur généré aléatoirement soit communiqué à
    l'utilisateur — il n'est jamais stocké en clair ni affiché une seconde
    fois ensuite (§3 spec, même principe que la création d'un utilisateur
    normal depuis Administration)."""
    message = (
        "Premier démarrage d'AKIBA APP.\n\n"
        "Un compte Administrateur a été créé :\n\n"
        f"Code PIN : {pin}\n\n"
        "Notez-le précieusement : il ne sera plus jamais affiché. "
        "Vous pourrez en créer d'autres et le changer depuis Administration > Utilisateurs."
    )
    ctypes.windll.user32.MessageBoxW(0, message, "AKIBA APP — Premier démarrage", 0x40)


def _commande_executable_actuel():
    """Commande (avec guillemets) permettant de relancer cette même
    application — utilisée comme cible de la tâche planifiée. En
    développement (pas encore empaqueté), rappelle l'interpréteur Python
    courant sur ce même script, pour pouvoir tester sans construire le .exe
    à chaque fois."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{Path(__file__).resolve()}"'


def _tache_planifiee_existe():
    resultat = subprocess.run(["schtasks", "/Query", "/TN", NOM_TACHE_PLANIFIEE], capture_output=True)
    return resultat.returncode == 0


def _installer_tache_planifiee():
    """Crée la tâche de sauvegarde automatique (toutes les 12h à partir de
    8h, donc environ 8h/20h) dès le tout premier lancement, sans aucune
    action du client. Échec toujours silencieux : l'application doit rester
    utilisable même si la création de la tâche échoue (droits Windows
    insuffisants, environnement inhabituel...) — la sauvegarde manuelle
    (bouton dans Administration) reste disponible dans ce cas."""
    if _tache_planifiee_existe():
        return
    try:
        cible = f"{_commande_executable_actuel()} --sauvegarde"
        subprocess.run(
            [
                "schtasks", "/Create", "/TN", NOM_TACHE_PLANIFIEE,
                "/TR", cible,
                "/SC", "HOURLY", "/MO", "12", "/ST", "08:00", "/F",
            ],
            capture_output=True,
        )
    except Exception:  # noqa: BLE001 - best-effort, ne doit jamais empêcher le lancement normal
        pass


def _executer_sauvegarde_silencieuse():
    """Appelée par la tâche planifiée (`--sauvegarde`), deux fois par jour,
    sans fenêtre ni interaction. Toute erreur est journalisée dans
    instance/sauvegardes/journal_sauvegarde_auto.log plutôt que de
    disparaître silencieusement (le Planificateur de tâches Windows
    n'affiche jamais la sortie d'une tâche à l'utilisateur)."""
    # Résolu directement depuis Config (pas depuis un `app` créé par
    # create_app()) : si create_app() elle-même échoue plus bas, on doit
    # quand même savoir où écrire le journal d'échec, plutôt que de
    # planter sans aucune trace avant même d'avoir pu journaliser quoi que
    # ce soit.
    dossier_sauvegardes = Path(Config.BACKUP_DIR)
    fichier_journal = dossier_sauvegardes / "journal_sauvegarde_auto.log"

    def journaliser(ligne):
        fichier_journal.parent.mkdir(parents=True, exist_ok=True)
        horodatage = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(fichier_journal, "a", encoding="utf-8") as f:
            f.write(f"[{horodatage}] {ligne}\n")

    try:
        from app import create_app
        from app.admin.backup_service import creer_sauvegarde

        app = create_app()
        with app.app_context():
            nom = creer_sauvegarde(app, _UtilisateurSysteme())
    except Exception:  # noqa: BLE001 - on veut tout attraper pour journaliser puis ressortir en échec
        journaliser("ÉCHEC de la sauvegarde automatique :\n" + traceback.format_exc())
        return 1

    journaliser(f"Sauvegarde automatique créée : {nom}")
    return 0


def _ecrire_journal_erreurs(message):
    """Journal d'erreurs "attrape-tout", écrit à côté de l'exécutable (donc
    toujours accessible même en fenêtre sans console) — pour qu'une erreur
    au tout premier démarrage (avant même l'ouverture de la fenêtre) laisse
    une trace exploitable plutôt qu'un plantage silencieux total."""
    horodatage = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fichier_journal = Config.INSTANCE_DIR / "journal_erreurs.txt"
    fichier_journal.parent.mkdir(parents=True, exist_ok=True)
    with open(fichier_journal, "a", encoding="utf-8") as f:
        f.write(f"[{horodatage}] {message}\n")


def main():
    from app import create_app
    from app.bootstrap import premier_demarrage_si_necessaire

    app = create_app()
    with app.app_context():
        pin_genere = premier_demarrage_si_necessaire()
    if pin_genere:
        _afficher_pin_premier_demarrage(pin_genere)

    _installer_tache_planifiee()

    port = _port_libre()

    serveur = threading.Thread(target=_demarrer_serveur, args=(app, port), daemon=True)
    serveur.start()

    import webview

    # Autorise les téléchargements natifs (exports Excel/PDF, factures...)
    # depuis la fenêtre pywebview, comme dans un navigateur classique —
    # décision explicite de l'utilisateur, pas le comportement par défaut
    # de pywebview qui bloque sinon silencieusement les téléchargements.
    webview.settings["ALLOW_DOWNLOADS"] = True

    webview.create_window(
        "AKIBA APP",
        f"http://127.0.0.1:{port}/",
        width=1366,
        height=768,
        min_size=(1024, 640),
    )
    webview.start(icon=CHEMIN_ICONE)


if __name__ == "__main__":
    if "--sauvegarde" in sys.argv:
        sys.exit(_executer_sauvegarde_silencieuse())

    # Attrape-tout : sans ceci, une erreur qui se produirait avant même la
    # création de la fenêtre (ex. WebView2 absent/cassé sur ce PC) ferait
    # planter l'exécutable en silence total — pas de console, pas de
    # fenêtre, aucune trace. Ici, l'erreur est au moins écrite dans
    # instance/journal_erreurs.txt (%LOCALAPPDATA%\AKIBA APP\ en exécutable).
    try:
        main()
    except Exception:
        _ecrire_journal_erreurs("ÉCHEC démarrage : " + traceback.format_exc().replace("\n", " | "))
        raise
