from datetime import datetime, timezone

from ..extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Inventaire(db.Model):
    """Inventaire général, par catégorie, ou par produit : stock théorique vs
    stock réel, écart calculé à la clôture. §9.3 spec."""

    __tablename__ = "inventaire"

    id = db.Column(db.Integer, primary_key=True)
    type_inventaire = db.Column(db.String(20), nullable=False)  # general | categorie | produit
    categorie_id = db.Column(db.Integer, db.ForeignKey("categorie.id"), nullable=True)

    statut = db.Column(db.String(20), nullable=False, default="ouvert")  # ouvert | cloture

    created_by_subprofile_id = db.Column(db.Integer, db.ForeignKey("sub_profile.id"), nullable=True)
    created_by_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    cloture_par_name = db.Column(db.String(120), nullable=True)
    cloture_le = db.Column(db.DateTime(timezone=True), nullable=True)

    categorie = db.relationship("Categorie")
    lignes = db.relationship("InventaireLigne", back_populates="inventaire", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Inventaire #{self.id} {self.type_inventaire} {self.statut}>"


class InventaireLigne(db.Model):
    __tablename__ = "inventaire_ligne"

    id = db.Column(db.Integer, primary_key=True)
    inventaire_id = db.Column(db.Integer, db.ForeignKey("inventaire.id"), nullable=False)
    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=False)

    stock_theorique = db.Column(db.Integer, nullable=False)
    stock_reel = db.Column(db.Integer, nullable=True)

    inventaire = db.relationship("Inventaire", back_populates="lignes")
    produit = db.relationship("Produit")

    @property
    def ecart(self):
        if self.stock_reel is None:
            return None
        return self.stock_reel - self.stock_theorique
