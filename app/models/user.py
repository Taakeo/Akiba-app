import json
import secrets
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db

PIN_LENGTH = 4


def utcnow():
    return datetime.now(timezone.utc)


def generer_pin():
    """Code PIN à 4 chiffres généré aléatoirement (générateur cryptographique,
    pas de choix humain — évite les PIN faibles/répétés type "0000")."""
    return "".join(secrets.choice("0123456789") for _ in range(PIN_LENGTH))


# Droits élémentaires réellement vérifiés dans l'app (@permission_required),
# avec libellé et icône pour l'écran d'édition des profils en Administration
# (§3 spec : "les droits associés à chaque profil sont entièrement
# modifiables par l'administrateur"). Le droit "*" (accès total) n'est pas
# une case à cocher parmi d'autres : il équivaut à cocher toutes les cases
# et reste réservé au profil Administrateur, géré séparément dans le
# formulaire plutôt que mélangé à cette liste.
PERMISSIONS_DISPONIBLES = [
    ("point_de_vente", "Point de Vente", "point_of_sale"),
    ("caisse", "Caisse", "payments"),
    ("achats", "Achats", "shopping_cart"),
    ("stocks", "Stocks", "inventory_2"),
    ("production", "Production", "precision_manufacturing"),
    ("rh", "Ressources humaines", "groups"),
    ("clients", "Clients", "person"),
    ("rapports", "Rapports", "bar_chart"),
    ("admin", "Administration (paramétrage, y compris cet écran)", "admin_panel_settings"),
]


# Profils par défaut à la première installation (§3.1 spec). L'administrateur
# peut ensuite renommer, ajouter ou modifier les droits de chaque profil.
DEFAULT_PROFILES = [
    {
        "code": "administrateur",
        "name": "Administrateur",
        "icon": "shield_person",
        "permissions": ["*"],
    },
    {
        "code": "responsable",
        "name": "Responsable",
        "icon": "manage_accounts",
        "permissions": [
            "point_de_vente",
            "caisse",
            "achats",
            "stocks",
            "production",
            "rapports",
            "rh",
            "clients",
        ],
    },
    {
        "code": "vendeur",
        "name": "Vendeur",
        "icon": "point_of_sale",
        "permissions": ["point_de_vente", "caisse"],
    },
    {
        "code": "comptable",
        "name": "Comptable",
        "icon": "account_balance",
        "permissions": ["rapports"],
    },
]


class Profile(db.Model):
    """Niveau 1 : définit les droits d'accès (quoi). Voir §3 spec."""

    __tablename__ = "profile"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(80), unique=True, nullable=False)
    icon = db.Column(db.String(50), nullable=False, default="badge")
    permissions_json = db.Column(db.Text, nullable=False, default="[]")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    sub_profiles = db.relationship(
        "SubProfile", back_populates="profile", order_by="SubProfile.full_name"
    )

    @property
    def permissions(self):
        return json.loads(self.permissions_json)

    @permissions.setter
    def permissions(self, value):
        self.permissions_json = json.dumps(list(value))

    def has_permission(self, code):
        perms = self.permissions
        return "*" in perms or code in perms

    def __repr__(self):
        return f"<Profile {self.code}>"


class SubProfile(UserMixin, db.Model):
    """Niveau 2 : identité individuelle réelle rattachée à un profil (qui).
    Connexion par code PIN personnel (§3 spec)."""

    __tablename__ = "sub_profile"

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("profile.id"), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    pin_hash = db.Column(db.String(255), nullable=False)

    is_active = db.Column(db.Boolean, nullable=False, default=True)
    suspended_at = db.Column(db.DateTime(timezone=True), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    profile = db.relationship("Profile", back_populates="sub_profiles")

    def set_pin(self, raw_pin):
        self.pin_hash = generate_password_hash(raw_pin)

    def check_pin(self, raw_pin):
        return check_password_hash(self.pin_hash, raw_pin)

    def suspend(self):
        self.is_active = False
        self.suspended_at = utcnow()

    def reactivate(self):
        self.is_active = True
        self.suspended_at = None

    def __repr__(self):
        return f"<SubProfile {self.full_name}>"
