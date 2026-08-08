import json
from datetime import datetime, timezone

from ..extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Vente(db.Model):
    """Vente enregistrée au Point de Vente. §6-7 spec."""

    __tablename__ = "vente"

    id = db.Column(db.Integer, primary_key=True)
    caisse_session_id = db.Column(db.Integer, db.ForeignKey("caisse_session.id"), nullable=False)
    type_tarif_id = db.Column(db.Integer, db.ForeignKey("type_tarif.id"), nullable=False)

    client_nom = db.Column(db.String(120), nullable=True)  # client de passage, pas de fiche (§5.2)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=True)  # client enregistré (facultatif)

    sous_total = db.Column(db.Integer, nullable=False, default=0)
    remise = db.Column(db.Integer, nullable=False, default=0)
    total = db.Column(db.Integer, nullable=False, default=0)
    # Part du total non payée immédiatement, mise sur le compte crédit du
    # client enregistré (§3.2 CDC v1 : "le logiciel conservera... crédits").
    # Historique, ne change jamais après coup.
    montant_credit = db.Column(db.Integer, nullable=False, default=0)
    # Ce qui reste dû SUR CETTE VENTE précisément, décrémenté (FIFO, la plus
    # ancienne vente à crédit en premier) à chaque paiement de crédit du
    # client — sert à ne plus afficher "à crédit" sur un reçu déjà soldé,
    # contrairement à montant_credit qui reste un fait historique figé.
    credit_solde_restant = db.Column(db.Integer, nullable=False, default=0)

    statut = db.Column(db.String(20), nullable=False, default="validee")  # validee | annulee
    commentaire = db.Column(db.Text, nullable=True)

    # Une vente ne peut appartenir qu'à une seule facture officielle : une
    # fois facturée, elle disparaît des choix proposés pour une nouvelle
    # facture (§ amélioration facturation, évite une double facturation).
    facture_id = db.Column(db.Integer, db.ForeignKey("facture.id"), nullable=True)

    created_by_subprofile_id = db.Column(db.Integer, db.ForeignKey("sub_profile.id"), nullable=True)
    created_by_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    caisse_session = db.relationship("CaisseSession")
    type_tarif = db.relationship("TypeTarif")
    client = db.relationship("Client", backref="ventes")
    facture = db.relationship("Facture", back_populates="ventes")
    lignes = db.relationship("LigneVente", back_populates="vente", cascade="all, delete-orphan")
    paiements = db.relationship("VentePaiement", back_populates="vente", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Vente #{self.id} {self.total}>"


class LigneVente(db.Model):
    __tablename__ = "ligne_vente"

    id = db.Column(db.Integer, primary_key=True)
    vente_id = db.Column(db.Integer, db.ForeignKey("vente.id"), nullable=False)
    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=False)

    # Snapshot de la hiérarchie comptable au moment de la vente (§4.3), pour que les
    # rapports restent stables même si la fiche produit est reclassée plus tard.
    produit_nom = db.Column(db.String(200), nullable=False)
    poste_id = db.Column(db.Integer, db.ForeignKey("poste.id"), nullable=False)
    projet_id = db.Column(db.Integer, db.ForeignKey("projet.id"), nullable=True)
    categorie_id = db.Column(db.Integer, db.ForeignKey("categorie.id"), nullable=False)
    sous_categorie_id = db.Column(db.Integer, db.ForeignKey("sous_categorie.id"), nullable=True)

    quantite = db.Column(db.Integer, nullable=False, default=1)
    prix_unitaire = db.Column(db.Integer, nullable=False)
    remise = db.Column(db.Integer, nullable=False, default=0)
    offert = db.Column(db.Boolean, nullable=False, default=False)
    commentaire = db.Column(db.String(255), nullable=True)
    total_ligne = db.Column(db.Integer, nullable=False, default=0)

    vente = db.relationship("Vente", back_populates="lignes")
    produit = db.relationship("Produit")

    def calculer_total(self):
        if self.offert:
            self.total_ligne = 0
        else:
            self.total_ligne = max(0, self.prix_unitaire * self.quantite - self.remise)
        return self.total_ligne


class TicketAttente(db.Model):
    """Panier mis en attente au Point de Vente : plusieurs clients arrivent
    en même temps, commandent tous, mais paient séparément — on ouvre un
    ticket nommé par client et on bascule de l'un à l'autre à volonté.
    Sauvegardé côté serveur à chaque modification pour survivre à une
    déconnexion, une coupure de courant ou un redémarrage du poste (§
    amélioration PDV), contrairement à un simple état JS en mémoire.

    Volontairement léger (lignes en JSON, pas de table normalisée comme
    LigneVente) : c'est un brouillon de travail, pas un enregistrement
    comptable — celui-ci n'existe qu'à l'encaissement, quand le ticket
    devient une vraie Vente et que ce brouillon est supprimé."""

    __tablename__ = "ticket_attente"

    id = db.Column(db.Integer, primary_key=True)
    caisse_session_id = db.Column(db.Integer, db.ForeignKey("caisse_session.id"), nullable=False)
    nom = db.Column(db.String(80), nullable=False)

    type_tarif_id = db.Column(db.Integer, db.ForeignKey("type_tarif.id"), nullable=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=True)
    client_nom = db.Column(db.String(120), nullable=True)

    lignes_json = db.Column(db.Text, nullable=False, default="[]")

    created_by_subprofile_id = db.Column(db.Integer, db.ForeignKey("sub_profile.id"), nullable=True)
    created_by_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    caisse_session = db.relationship("CaisseSession")
    type_tarif = db.relationship("TypeTarif")
    client = db.relationship("Client")

    @property
    def lignes(self):
        return json.loads(self.lignes_json)

    @lignes.setter
    def lignes(self, value):
        self.lignes_json = json.dumps(list(value))

    def __repr__(self):
        return f"<TicketAttente {self.nom}>"


class FactureCompteur(db.Model):
    """Compteur de numérotation séquentielle des factures officielles (ligne
    unique, id=1) — une numérotation officielle ne doit jamais avoir de trou
    ni se répéter, donc un compteur dédié incrémenté de façon atomique plutôt
    que de dériver le numéro de MAX(id) (qui se décale si une facture est un
    jour supprimée pour cause d'erreur de saisie)."""

    __tablename__ = "facture_compteur"

    id = db.Column(db.Integer, primary_key=True)
    dernier_numero = db.Column(db.Integer, nullable=False, default=0)

    @classmethod
    def numero_suivant(cls):
        compteur = db.session.get(cls, 1)
        if compteur is None:
            compteur = cls(id=1, dernier_numero=0)
            db.session.add(compteur)
        compteur.dernier_numero += 1
        db.session.flush()
        return f"FA-{compteur.dernier_numero:06d}"


class Facture(db.Model):
    """Facture officielle émise à partir d'un ou plusieurs tickets de vente
    (§ amélioration facturation) : numérotée séquentiellement, nom/adresse du
    client obligatoires, coordonnées légales d'Akiba figées au moment de
    l'émission (un changement ultérieur des coordonnées dans Administration
    ne doit jamais modifier une facture déjà émise)."""

    __tablename__ = "facture"

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(20), unique=True, nullable=False)
    date_emission = db.Column(db.Date, nullable=False, default=lambda: utcnow().date())

    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    client_nom = db.Column(db.String(150), nullable=False)
    client_adresse = db.Column(db.Text, nullable=False)

    # Coordonnées légales d'Akiba au moment de l'émission — copie figée de
    # ParametresLegaux, jamais une référence vivante (voir docstring).
    emetteur_raison_sociale = db.Column(db.String(200), nullable=False)
    emetteur_adresse = db.Column(db.Text, nullable=True)
    emetteur_telephone = db.Column(db.String(50), nullable=True)
    emetteur_email = db.Column(db.String(120), nullable=True)
    emetteur_nif = db.Column(db.String(50), nullable=True)
    emetteur_stat = db.Column(db.String(50), nullable=True)
    emetteur_rcs = db.Column(db.String(50), nullable=True)

    sous_total = db.Column(db.Integer, nullable=False, default=0)
    remise = db.Column(db.Integer, nullable=False, default=0)
    total = db.Column(db.Integer, nullable=False, default=0)

    created_by_subprofile_id = db.Column(db.Integer, db.ForeignKey("sub_profile.id"), nullable=True)
    created_by_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    client = db.relationship("Client")
    ventes = db.relationship("Vente", back_populates="facture", order_by="Vente.id")

    def __repr__(self):
        return f"<Facture {self.numero}>"


class VentePaiement(db.Model):
    """Une vente peut être réglée avec plusieurs moyens de paiement combinés. §7.6 spec."""

    __tablename__ = "vente_paiement"

    id = db.Column(db.Integer, primary_key=True)
    vente_id = db.Column(db.Integer, db.ForeignKey("vente.id"), nullable=False)
    moyen_paiement_id = db.Column(db.Integer, db.ForeignKey("moyen_paiement.id"), nullable=False)
    montant = db.Column(db.Integer, nullable=False)

    vente = db.relationship("Vente", back_populates="paiements")
    moyen_paiement = db.relationship("MoyenPaiement")
