from datetime import datetime, timezone

from ..extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Fournisseur(db.Model):
    """Fiche fournisseur : coordonnées, historique des achats via Achat. §5.3 spec."""

    __tablename__ = "fournisseur"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    telephone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    adresse = db.Column(db.Text, nullable=True)
    observations = db.Column(db.Text, nullable=True)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    def __repr__(self):
        return f"<Fournisseur {self.name}>"
