from datetime import datetime, timezone

from ..extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Achat(db.Model):
    """Achat de stock (augmente le stock) ou dépense générale (aucun effet sur
    le stock, rattachée obligatoirement à poste/catégorie). §8.1-8.2 spec."""

    __tablename__ = "achat"

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(150), nullable=True)
    type_achat = db.Column(db.String(10), nullable=False)  # stock | depense

    # Renseigné uniquement si payé en espèces depuis la caisse physique
    # pendant une session ouverte — sert à faire apparaître l'achat dans
    # l'historique de la session ET à le déduire du contenu théorique du
    # tiroir à la clôture (§7.2 spec : sorties d'argent de la session).
    caisse_session_id = db.Column(db.Integer, db.ForeignKey("caisse_session.id"), nullable=True)

    fournisseur_id = db.Column(db.Integer, db.ForeignKey("fournisseur.id"), nullable=True)
    date_achat = db.Column(db.Date, nullable=False)

    poste_id = db.Column(db.Integer, db.ForeignKey("poste.id"), nullable=False)
    projet_id = db.Column(db.Integer, db.ForeignKey("projet.id"), nullable=True)
    categorie_id = db.Column(db.Integer, db.ForeignKey("categorie.id"), nullable=False)
    sous_categorie_id = db.Column(db.Integer, db.ForeignKey("sous_categorie.id"), nullable=True)

    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=True)
    quantite = db.Column(db.Integer, nullable=True)
    prix_unitaire = db.Column(db.Integer, nullable=True)
    montant_total = db.Column(db.Integer, nullable=False)

    moyen_paiement_id = db.Column(db.Integer, db.ForeignKey("moyen_paiement.id"), nullable=False)
    observations = db.Column(db.Text, nullable=True)

    created_by_subprofile_id = db.Column(db.Integer, db.ForeignKey("sub_profile.id"), nullable=True)
    created_by_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    fournisseur = db.relationship("Fournisseur")
    poste = db.relationship("Poste")
    projet = db.relationship("Projet")
    categorie = db.relationship("Categorie")
    sous_categorie = db.relationship("SousCategorie")
    produit = db.relationship("Produit")
    moyen_paiement = db.relationship("MoyenPaiement")
    documents = db.relationship("AchatDocument", back_populates="achat", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Achat #{self.id} {self.type_achat} {self.montant_total}>"


class AchatRecurrent(db.Model):
    """Modèle d'achat récurrent (bois, quincaillerie, bouffe, wifi...) : mémorise
    le classement habituel d'une dépense pour la relancer en un clic au lieu
    de tout ressaisir à chaque fois. Ne déclenche rien automatiquement — sert
    uniquement à préremplir le formulaire d'achat."""

    __tablename__ = "achat_recurrent"

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(120), nullable=False)
    type_achat = db.Column(db.String(10), nullable=False)  # stock | depense

    fournisseur_id = db.Column(db.Integer, db.ForeignKey("fournisseur.id"), nullable=True)
    poste_id = db.Column(db.Integer, db.ForeignKey("poste.id"), nullable=False)
    projet_id = db.Column(db.Integer, db.ForeignKey("projet.id"), nullable=True)
    categorie_id = db.Column(db.Integer, db.ForeignKey("categorie.id"), nullable=False)
    sous_categorie_id = db.Column(db.Integer, db.ForeignKey("sous_categorie.id"), nullable=True)

    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=True)
    quantite_habituelle = db.Column(db.Integer, nullable=True)
    prix_unitaire_habituel = db.Column(db.Integer, nullable=True)
    montant_habituel = db.Column(db.Integer, nullable=True)

    moyen_paiement_id = db.Column(db.Integer, db.ForeignKey("moyen_paiement.id"), nullable=True)

    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    fournisseur = db.relationship("Fournisseur")
    poste = db.relationship("Poste")
    projet = db.relationship("Projet")
    categorie = db.relationship("Categorie")
    sous_categorie = db.relationship("SousCategorie")
    produit = db.relationship("Produit")
    moyen_paiement = db.relationship("MoyenPaiement")

    def __repr__(self):
        return f"<AchatRecurrent {self.nom}>"


class AchatDocument(db.Model):
    """Facture, devis, photo, bon de livraison joints à un achat. §8.3 spec."""

    __tablename__ = "achat_document"

    id = db.Column(db.Integer, primary_key=True)
    achat_id = db.Column(db.Integer, db.ForeignKey("achat.id"), nullable=False)
    nom_original = db.Column(db.String(255), nullable=False)
    nom_fichier = db.Column(db.String(255), nullable=False)  # nom sur disque (instance/uploads/achats/)
    uploaded_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    achat = db.relationship("Achat", back_populates="documents")
