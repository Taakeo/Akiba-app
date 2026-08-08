"""Utilitaires PDF partagés entre modules (factures, rapports) — pour
l'instant uniquement le logo Akiba en en-tête, réutilisé identique partout."""

from pathlib import Path

from flask import current_app
from PIL import Image as PILImage
from reportlab.lib.units import mm
from reportlab.platypus import Image


def chemin_logo():
    return Path(current_app.root_path) / "static" / "vendor" / "logo" / "akiba-logo.png"


def logo_flowable(largeur_mm=35):
    """Logo Akiba en flowable ReportLab, proportions conservées — assez
    grand pour être lisible en en-tête de document, jamais démesuré
    (retour utilisateur explicite : "assez grande mais pas immense")."""
    chemin = chemin_logo()
    if not chemin.exists():
        return None
    with PILImage.open(chemin) as img:
        ratio = img.height / img.width
    largeur = largeur_mm * mm
    hauteur = largeur * ratio
    return Image(str(chemin), width=largeur, height=hauteur)
