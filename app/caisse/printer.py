"""Ouverture physique du tiroir-caisse via l'imprimante de tickets (§6.5,
§7.5 spec) : le tiroir n'a pas de commande dédiée, il est câblé sur
l'imprimante RJ11/RJ12 et s'ouvre uniquement par une impulsion électrique
envoyée DANS un job d'impression (commande ESC/POS standard "kick drawer").
On envoie donc un job d'impression minimal (aucun texte, juste la commande)
en RAW directement au spouleur Windows, sans passer par GDI — c'est la
technique standard pour piloter une imprimante ticket ESC/POS depuis
Windows, y compris pour une "impression à blanc" indépendante de toute
vente (§7.5 : le tiroir doit pouvoir s'ouvrir sans transaction)."""

# ESC p m t1 t2 — "kick drawer" : m=0 sélectionne la broche 2 du connecteur
# RJ11/RJ12 (quasi toujours celle câblée sur le tiroir dans ce type
# d'installation), t1/t2 réglent la durée de l'impulsion. Valeurs standard
# reprises de la doc ESC/POS (Epson et compatibles, dont les clones
# génériques type POS-80/POS-58).
COMMANDE_OUVERTURE_TIROIR = b"\x1b\x70\x00\x19\xfa"


class ImprimanteError(Exception):
    pass


def ouvrir_tiroir(nom_imprimante):
    """Envoie la commande d'ouverture du tiroir à l'imprimante Windows
    nommée `nom_imprimante`. Lève ImprimanteError avec un message explicite
    si l'imprimante n'est pas installée/accessible — jamais d'exception
    technique brute remontée jusqu'à l'utilisateur."""
    try:
        import win32print
    except ImportError as exc:
        raise ImprimanteError(
            "Module pywin32 indisponible (fonctionnalité réservée à Windows)."
        ) from exc

    try:
        handle = win32print.OpenPrinter(nom_imprimante)
    except Exception as exc:  # noqa: BLE001 - message utilisateur, pas une trace pywin32
        raise ImprimanteError(
            f"Imprimante « {nom_imprimante} » introuvable. Vérifiez qu'elle est bien "
            "installée dans Windows (Paramètres > Imprimantes) sous ce nom exact, "
            "et que le nom configuré en Administration correspond."
        ) from exc

    try:
        job_id = win32print.StartDocPrinter(handle, 1, ("Ouverture tiroir-caisse", None, "RAW"))
        try:
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, COMMANDE_OUVERTURE_TIROIR)
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
        return job_id
    except Exception as exc:  # noqa: BLE001 - idem, message utilisateur
        raise ImprimanteError(f"Échec de l'envoi à l'imprimante « {nom_imprimante} » : {exc}") from exc
    finally:
        win32print.ClosePrinter(handle)
