from datetime import datetime, timezone

from ..extensions import db


def utcnow():
    return datetime.now(timezone.utc)


TYPES_CLIENT = [
    ("enregistre", "Client enregistré"),
    ("adherent", "Adhérent"),
    ("grossiste", "Grossiste"),
    ("agence_voyage", "Agence de voyage"),
]


class Client(db.Model):
    """Fiche client (hors client de passage, qui reste un simple texte libre
    sur la vente — §3.2 CDC v1, §5.2 spec). Historique des achats et crédits
    consultable via les relations `ventes` / `paiements`."""

    __tablename__ = "client"

    id = db.Column(db.Integer, primary_key=True)
    type_client = db.Column(db.String(30), nullable=False, default="enregistre")
    nom = db.Column(db.String(150), nullable=False)
    telephone = db.Column(db.String(50), nullable=True)
    adresse = db.Column(db.Text, nullable=True)
    email = db.Column(db.String(120), nullable=True)
    observations = db.Column(db.Text, nullable=True)

    # Solde dû par le client (ventes à crédit non encore payées). Mis à jour
    # de façon transactionnelle, comme le solde d'un compte financier.
    solde_credit = db.Column(db.Integer, nullable=False, default=0)

    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    def __repr__(self):
        return f"<Client {self.nom}>"


class ClientPaiement(db.Model):
    """Paiement effectué par le client pour réduire son solde de crédit."""

    __tablename__ = "client_paiement"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    montant = db.Column(db.Integer, nullable=False)
    moyen_paiement_id = db.Column(db.Integer, db.ForeignKey("moyen_paiement.id"), nullable=False)
    date_paiement = db.Column(db.Date, nullable=False)
    observations = db.Column(db.Text, nullable=True)

    created_by_subprofile_id = db.Column(db.Integer, db.ForeignKey("sub_profile.id"), nullable=True)
    created_by_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    client = db.relationship("Client", backref="paiements")
    moyen_paiement = db.relationship("MoyenPaiement")

    def __repr__(self):
        return f"<ClientPaiement {self.montant}>"
