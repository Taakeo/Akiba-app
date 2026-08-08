"""Amorçage du tout premier lancement de l'exécutable packagé (§3 spec).

Volontairement distinct de `flask seed-db` (app/cli.py, réservé au
développement) : ce dernier crée un administrateur avec le PIN fixe "0000"
et un catalogue de démonstration, pratique pour développer/tester mais
inadapté à une vraie association — un PIN connu d'avance sur une base de
production serait une faille de sécurité, et personne chez Akiba ne doit
se retrouver avec des produits fictifs à supprimer à la main.

Ici : uniquement les 4 profils par défaut + un compte Administrateur avec un
PIN aléatoire (même générateur cryptographique que partout ailleurs dans
l'app), révélé une seule fois à l'utilisateur final."""

from .extensions import db
from .models import DEFAULT_PROFILES, Profile, SubProfile
from .models.user import generer_pin


def premier_demarrage_si_necessaire():
    """Si la base est vraiment vierge (aucun profil), crée les profils par
    défaut et un compte Administrateur avec un PIN aléatoire. Retourne ce
    PIN (à afficher une seule fois) si l'amorçage a eu lieu, sinon None."""
    if Profile.query.count() > 0:
        return None

    for data in DEFAULT_PROFILES:
        profile = Profile(code=data["code"], name=data["name"], icon=data["icon"])
        profile.permissions = data["permissions"]
        db.session.add(profile)
    db.session.commit()

    admin_profile = Profile.query.filter_by(code="administrateur").first()
    pin = generer_pin()
    admin = SubProfile(profile_id=admin_profile.id, full_name="Administrateur")
    admin.set_pin(pin)
    db.session.add(admin)
    db.session.commit()

    return pin
