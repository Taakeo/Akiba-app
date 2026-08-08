from datetime import datetime, timezone

from ..extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Fabrication(db.Model):
    """Déclaration de fabrication (chocolat, café, huiles, épices...). §10 spec.

    La validation ajoute automatiquement le produit fabriqué au stock
    (mouvement tracé, motif "fabrication") et met à jour la traçabilité
    alimentaire courante du produit (lot, date de fabrication, DDM/DLC)."""

    __tablename__ = "fabrication"

    id = db.Column(db.Integer, primary_key=True)
    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=False)
    quantite = db.Column(db.Integer, nullable=False)
    responsable_nom = db.Column(db.String(120), nullable=False)
    date_fabrication = db.Column(db.Date, nullable=False)

    numero_lot = db.Column(db.String(64), nullable=True)
    ddm_dlc = db.Column(db.Date, nullable=True)
    observations = db.Column(db.Text, nullable=True)

    created_by_subprofile_id = db.Column(db.Integer, db.ForeignKey("sub_profile.id"), nullable=True)
    created_by_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    produit = db.relationship("Produit")

    def __repr__(self):
        return f"<Fabrication #{self.id} {self.quantite} #{self.produit_id}>"
