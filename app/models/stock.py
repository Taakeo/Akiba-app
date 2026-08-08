from datetime import datetime, timezone

from ..extensions import db


def utcnow():
    return datetime.now(timezone.utc)


MOTIFS_ENTREE = [
    ("achat", "Achat"),
    ("fabrication", "Fabrication"),
    ("retour_client", "Retour client"),
    ("don", "Don"),
    ("correction", "Correction / inventaire"),
]

MOTIFS_SORTIE = [
    ("vente", "Vente"),
    ("offert", "Offert / dégustation"),
    ("perte", "Perte"),
    ("consommation_interne", "Consommation interne"),
    ("don", "Don"),
    ("correction", "Correction / inventaire"),
]


class MouvementStock(db.Model):
    """Grand livre des mouvements de stock : chaque entrée/sortie trace date,
    utilisateur, quantité, motif (§9.2 spec). Alimenté automatiquement par les
    achats de stock et les ventes, ou saisi manuellement (perte, don, correction)."""

    __tablename__ = "mouvement_stock"

    id = db.Column(db.Integer, primary_key=True)
    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=False)

    type_mouvement = db.Column(db.String(10), nullable=False)  # entree | sortie
    motif = db.Column(db.String(30), nullable=False)
    quantite = db.Column(db.Integer, nullable=False)
    commentaire = db.Column(db.String(255), nullable=True)

    # Origine du mouvement (achat, vente, inventaire...), facultatif et libre :
    # permet de remonter à la pièce source sans coupler le modèle à chaque module.
    reference_type = db.Column(db.String(30), nullable=True)
    reference_id = db.Column(db.Integer, nullable=True)

    created_by_subprofile_id = db.Column(db.Integer, db.ForeignKey("sub_profile.id"), nullable=True)
    created_by_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    produit = db.relationship("Produit")

    def __repr__(self):
        return f"<MouvementStock {self.type_mouvement} {self.quantite} #{self.produit_id}>"


def enregistrer_mouvement(produit, type_mouvement, motif, quantite, current_user, commentaire=None,
                           reference_type=None, reference_id=None):
    """Applique le mouvement au stock du produit et journalise la ligne (§9.1-9.2).
    `quantite` est toujours positive ; le signe est déterminé par `type_mouvement`."""
    if quantite <= 0:
        raise ValueError("La quantité doit être positive.")

    if type_mouvement == "entree":
        produit.stock_quantite += quantite
    elif type_mouvement == "sortie":
        produit.stock_quantite -= quantite
    else:
        raise ValueError("type_mouvement doit être 'entree' ou 'sortie'.")

    mouvement = MouvementStock(
        produit_id=produit.id,
        type_mouvement=type_mouvement,
        motif=motif,
        quantite=quantite,
        commentaire=commentaire,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_subprofile_id=current_user.id,
        created_by_name=current_user.full_name,
    )
    db.session.add(mouvement)
    return mouvement
