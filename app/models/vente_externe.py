from datetime import datetime, timezone

from ..extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class VenteExterne(db.Model):
    """Rentrée d'argent ponctuelle et inhabituelle, hors PDV (ex. vente
    d'objets non catalogués comme des meubles, produits de la ferme, dons,
    financements). Réservée à Administrateur + Responsable (droit
    "ventes_externes" — voir app/models/user.py::PERMISSIONS_DISPONIBLES).

    Calquée sur Achat (même classement poste/catégorie/sous-catégorie/projet)
    mais recette au lieu de dépense, client au lieu de fournisseur. Pas de
    champ "type" séparé stock/libre comme sur Achat : la présence de
    `produit_id` suffit à distinguer une vente d'un produit catalogué (déduit
    le stock, comme une vente PDV) d'une entrée libre sans effet stock (objet
    non catalogué, don, financement).

    Le compte crédité est celui auquel `moyen_paiement_id` est rattaché
    (Compte Akiba, BMOI, Orange Money...) — jamais le tiroir-caisse physique
    du PDV, exclu de la liste des moyens proposés (voir
    app/ventes_externes/routes.py::_populate_choices), exactement le même
    mécanisme que pour un achat payé "Compte Akiba (coffre-fort)"."""

    __tablename__ = "vente_externe"

    id = db.Column(db.Integer, primary_key=True)

    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=True)
    # Client de passage : texte libre, comme au PDV — pas de fiche permanente.
    client_nom = db.Column(db.String(150), nullable=True)

    date_vente = db.Column(db.Date, nullable=False)

    poste_id = db.Column(db.Integer, db.ForeignKey("poste.id"), nullable=False)
    projet_id = db.Column(db.Integer, db.ForeignKey("projet.id"), nullable=True)
    categorie_id = db.Column(db.Integer, db.ForeignKey("categorie.id"), nullable=False)
    sous_categorie_id = db.Column(db.Integer, db.ForeignKey("sous_categorie.id"), nullable=True)

    # Renseigné seulement si l'objet vendu est un produit catalogué (déduit
    # alors le stock) — laissé vide pour un objet non catalogué (meuble...).
    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=True)
    quantite = db.Column(db.Integer, nullable=True)
    prix_unitaire = db.Column(db.Integer, nullable=True)
    montant_total = db.Column(db.Integer, nullable=False)

    moyen_paiement_id = db.Column(db.Integer, db.ForeignKey("moyen_paiement.id"), nullable=False)
    observations = db.Column(db.Text, nullable=True)

    # Annulation (droit "corrections", app/ventes_externes/routes.py::annuler) :
    # reverse le stock (si produit catalogué) et débite le compte crédité à
    # l'origine — voir Achat.is_annule pour le même principe.
    is_annule = db.Column(db.Boolean, nullable=False, default=False)
    annule_motif = db.Column(db.Text, nullable=True)
    annule_par_nom = db.Column(db.String(120), nullable=True)
    annule_le = db.Column(db.DateTime(timezone=True), nullable=True)

    created_by_subprofile_id = db.Column(db.Integer, db.ForeignKey("sub_profile.id"), nullable=True)
    created_by_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    client = db.relationship("Client")
    poste = db.relationship("Poste")
    projet = db.relationship("Projet")
    categorie = db.relationship("Categorie")
    sous_categorie = db.relationship("SousCategorie")
    produit = db.relationship("Produit")
    moyen_paiement = db.relationship("MoyenPaiement")

    def __repr__(self):
        return f"<VenteExterne #{self.id} {self.montant_total}>"
