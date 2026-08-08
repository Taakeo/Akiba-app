"""Point d'entrée du déploiement "fenêtre native" (§2.1, §15.1 spec —
décision de déploiement tranchée par l'utilisateur : pywebview + PyInstaller,
téléchargements autorisés comme dans un navigateur).

Fait tourner l'application Flask via Waitress (serveur WSGI de production,
pas le serveur de dev Flask) sur un port local libre, puis ouvre une
fenêtre native pointant dessus — aucun navigateur externe à lancer, aucune
adresse à taper, conforme à la contrainte "100% hors ligne, poste unique"
(§2). C'est ce fichier (compilé en .exe par PyInstaller) que l'utilisateur
final double-clique."""

import ctypes
import socket
import threading

import webview

from app import create_app
from app.bootstrap import premier_demarrage_si_necessaire
from config import BASE_DIR

CHEMIN_ICONE = str(BASE_DIR / "app" / "static" / "vendor" / "logo" / "akiba.ico")


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


def main():
    app = create_app()
    with app.app_context():
        pin_genere = premier_demarrage_si_necessaire()
    if pin_genere:
        _afficher_pin_premier_demarrage(pin_genere)

    port = _port_libre()

    serveur = threading.Thread(target=_demarrer_serveur, args=(app, port), daemon=True)
    serveur.start()

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
    main()
