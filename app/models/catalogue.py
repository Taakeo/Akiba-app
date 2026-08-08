import math
from datetime import datetime, timezone

from ..extensions import db


def utcnow():
    return datetime.now(timezone.utc)


def arrondir_centaine_superieure(montant):
    """Arrondit un montant (Ariary, toujours en entier) à la centaine
    supérieure — utilisé pour tout prix calculé automatiquement en
    pourcentage, jamais pour un prix saisi à la main."""
    return math.ceil(montant / 100) * 100


class Poste(db.Model):
    """Pôle d'activité d'Akiba (Boutique, Agriculture, Tourisme...). §4.3 spec."""

    __tablename__ = "poste"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    icon = db.Column(db.String(50), nullable=False, default="storefront")
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    def __repr__(self):
        return f"<Poste {self.name}>"


class Projet(db.Model):
    """Projet financé par un partenaire, rattachement facultatif. §4.3 spec."""

    __tablename__ = "projet"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    def __repr__(self):
        return f"<Projet {self.name}>"


class Categorie(db.Model):
    """Catégorie de produits/dépenses, rattachée à un seul Poste (§4.3, §6.3
    spec) — reprend la structure comptable réelle d'Akiba (ex. "Vanille",
    "Chocolat" sous Boutique_Atelier ; "Salaires_dispensaire" sous
    Dispensaire) : deux postes différents peuvent avoir une catégorie de
    même nom, d'où l'unicité sur (poste_id, name) et non plus sur name seul."""

    __tablename__ = "categorie"

    id = db.Column(db.Integer, primary_key=True)
    poste_id = db.Column(db.Integer, db.ForeignKey("poste.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    icon = db.Column(db.String(50), nullable=False, default="category")
    ordre = db.Column(db.Integer, nullable=False, default=0)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    poste = db.relationship("Poste")
    sous_categories = db.relationship(
        "SousCategorie", back_populates="categorie", order_by="SousCategorie.name"
    )

    __table_args__ = (db.UniqueConstraint("poste_id", "name"),)

    def __repr__(self):
        return f"<Categorie {self.name}>"


class SousCategorie(db.Model):
    __tablename__ = "sous_categorie"

    id = db.Column(db.Integer, primary_key=True)
    categorie_id = db.Column(db.Integer, db.ForeignKey("categorie.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    categorie = db.relationship("Categorie", back_populates="sous_categories")

    __table_args__ = (db.UniqueConstraint("categorie_id", "name"),)

    def __repr__(self):
        return f"<SousCategorie {self.name}>"


def sous_categories_par_categorie():
    """{ categorie_id: [{"id": ..., "name": ...}, ...] } pour filtrer un
    <select> de sous-catégories en JS selon la catégorie choisie (évite une
    liste plate mélangeant toutes les catégories)."""
    mapping = {}
    sous_categories = SousCategorie.query.filter_by(is_archived=False).order_by(SousCategorie.name).all()
    for sc in sous_categories:
        mapping.setdefault(str(sc.categorie_id), []).append({"id": sc.id, "name": sc.name})
    return mapping


def categories_par_poste():
    """{ poste_id: [{"id": ..., "name": ...}, ...] } pour filtrer un <select>
    de catégories en JS selon le poste choisi — même principe que
    sous_categories_par_categorie(), un niveau au-dessus (§4.3 spec)."""
    mapping = {}
    categories = Categorie.query.filter_by(is_archived=False).order_by(Categorie.ordre, Categorie.name).all()
    for c in categories:
        mapping.setdefault(str(c.poste_id), []).append({"id": c.id, "name": c.name})
    return mapping


class TypeTarif(db.Model):
    """Type de tarif de vente (standard, adhérent, grossiste...), extensible. §6.4 spec."""

    __tablename__ = "type_tarif"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    label = db.Column(db.String(80), nullable=False)
    ordre = db.Column(db.Integer, nullable=False, default=0)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)

    # Rabais automatique optionnel (ex. Adhérent = -10%) : calculé à partir du
    # "prix de référence" de chaque produit, arrondi à la centaine supérieure.
    # N'intervient que si aucun prix manuel n'a été saisi pour ce produit sur
    # ce tarif — un prix saisi à la main prime toujours. Désactivable sans
    # perdre le pourcentage renseigné (rabais_actif=False le neutralise).
    pourcentage_rabais = db.Column(db.Integer, nullable=True)
    rabais_actif = db.Column(db.Boolean, nullable=False, default=False)

    def __repr__(self):
        return f"<TypeTarif {self.code}>"


class Produit(db.Model):
    """Fiche produit créée une seule fois, réutilisée dans tous les modules. §5.1 spec."""

    __tablename__ = "produit"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)

    categorie_id = db.Column(db.Integer, db.ForeignKey("categorie.id"), nullable=False)
    sous_categorie_id = db.Column(db.Integer, db.ForeignKey("sous_categorie.id"), nullable=True)
    poste_id = db.Column(db.Integer, db.ForeignKey("poste.id"), nullable=False)
    projet_id = db.Column(db.Integer, db.ForeignKey("projet.id"), nullable=True)
    fournisseur_principal_id = db.Column(db.Integer, db.ForeignKey("fournisseur.id"), nullable=True)

    unite = db.Column(db.String(30), nullable=False, default="unité")
    prix_achat = db.Column(db.Integer, nullable=True)
    # Prix de base servant de référence aux tarifs calculés en pourcentage
    # (ex. Adhérent -10%). Indépendant du prix d'achat et des prix fixés à la
    # main par tarif ci-dessous, qui restent toujours prioritaires.
    prix_reference = db.Column(db.Integer, nullable=True)
    seuil_alerte = db.Column(db.Integer, nullable=True)
    stock_quantite = db.Column(db.Integer, nullable=False, default=0)
    # Pour les produits qui ne sont pas un stock physique décomptable (ex. une
    # visite guidée) : la vente ne décrémente jamais le stock et ne peut
    # jamais être bloquée par une rupture.
    stock_illimite = db.Column(db.Boolean, nullable=False, default=False)
    # Prix libre (§6.4 spec) : au lieu d'utiliser prix_pour(tarif), le PDV
    # demande un montant saisi à la main à chaque ajout au panier (ex. un
    # pourboire, dont le montant n'est jamais fixe). Incompatible avec les
    # tarifs par type de client, qui restent ignorés pour ce produit.
    prix_libre = db.Column(db.Boolean, nullable=False, default=False)

    photo_path = db.Column(db.String(255), nullable=True)
    code_barres = db.Column(db.String(64), nullable=True)

    # Traçabilité alimentaire (§5.1, §10.3)
    numero_lot = db.Column(db.String(64), nullable=True)
    date_fabrication = db.Column(db.Date, nullable=True)
    ddm_dlc = db.Column(db.Date, nullable=True)

    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    categorie = db.relationship("Categorie")
    sous_categorie = db.relationship("SousCategorie")
    poste = db.relationship("Poste")
    projet = db.relationship("Projet")
    fournisseur_principal = db.relationship("Fournisseur")
    prix_tarifs = db.relationship(
        "PrixProduit", back_populates="produit", cascade="all, delete-orphan"
    )

    def prix_pour(self, type_tarif_code):
        for prix in self.prix_tarifs:
            if prix.type_tarif.code == type_tarif_code:
                return prix.montant

        # Pas de prix saisi à la main pour ce tarif : si le tarif a un rabais
        # automatique actif et que ce produit a un prix de référence, on
        # calcule le prix (arrondi à la centaine supérieure) plutôt que de
        # rendre le tarif indisponible pour ce produit.
        tarif = TypeTarif.query.filter_by(code=type_tarif_code, is_archived=False).first()
        if tarif and tarif.rabais_actif and tarif.pourcentage_rabais and self.prix_reference:
            return arrondir_centaine_superieure(
                self.prix_reference * (100 - tarif.pourcentage_rabais) / 100
            )
        return None

    @property
    def statut_stock(self):
        if self.stock_illimite:
            return "illimite"
        if self.stock_quantite <= 0:
            return "rupture"
        if self.seuil_alerte is not None and self.stock_quantite <= self.seuil_alerte:
            return "faible"
        return "ok"

    def __repr__(self):
        return f"<Produit {self.name}>"


class PrixProduit(db.Model):
    """Tarif de vente d'un produit pour un type de tarif donné (standard, adhérent...). §5.1 spec."""

    __tablename__ = "prix_produit"

    id = db.Column(db.Integer, primary_key=True)
    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=False)
    type_tarif_id = db.Column(db.Integer, db.ForeignKey("type_tarif.id"), nullable=False)
    montant = db.Column(db.Integer, nullable=False)

    produit = db.relationship("Produit", back_populates="prix_tarifs")
    type_tarif = db.relationship("TypeTarif")

    __table_args__ = (db.UniqueConstraint("produit_id", "type_tarif_id"),)
