from datetime import datetime, timezone

from ..extensions import db


def utcnow():
    return datetime.now(timezone.utc)


TYPES_CONTRAT = ["CDI", "CDD", "Hebdomadaire", "Journalier", "Stagiaire", "Bénévole"]

TYPES_REMUNERATION = [
    ("salaire_mensuel", "Salaire mensuel"),
    ("salaire_hebdomadaire", "Salaire hebdomadaire"),
    ("remuneration_journaliere", "Rémunération journalière"),
    ("avance", "Avance"),
    ("prime", "Prime"),
    ("retenue", "Retenue"),
]

# Fréquence de versement habituelle d'un salarié — sert à calculer ce qui lui
# est dû entre deux paiements (§ système de paye). "Hebdomadaire" mis en
# premier : c'est en pratique le rythme le plus courant chez Akiba.
FREQUENCES_REMUNERATION = [
    ("hebdomadaire", "Hebdomadaire"),
    ("mensuel", "Mensuel"),
    ("journalier", "Journalier"),
]

TYPES_ABSENCE = [
    ("maladie", "Maladie"),
    ("conge_paye", "Congé payé"),
    ("conge_sans_solde", "Congé sans solde"),
    ("injustifiee", "Absence injustifiée"),
    ("autre", "Autre"),
]


class Salarie(db.Model):
    """Fiche salarié : identité, contrat, rattachement poste/projet. §5.4 spec."""

    __tablename__ = "salarie"

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(150), nullable=False)
    telephone = db.Column(db.String(50), nullable=True)
    fonction = db.Column(db.String(120), nullable=True)
    type_contrat = db.Column(db.String(30), nullable=True)
    date_embauche = db.Column(db.Date, nullable=True)

    poste_id = db.Column(db.Integer, db.ForeignKey("poste.id"), nullable=True)
    projet_id = db.Column(db.Integer, db.ForeignKey("projet.id"), nullable=True)

    # Facultatifs : un salarié peut être créé sans salaire fixé (ex. bénévole,
    # à négocier plus tard). Quand renseigné, sert de référence pour calculer
    # ce qui est dû entre deux versements (§ compte salarié).
    salaire_habituel = db.Column(db.Integer, nullable=True)
    frequence_remuneration = db.Column(db.String(20), nullable=True)
    # Quota annuel de congés payés — initialisé depuis ParametresRH à la
    # création, ajustable individuellement (ex. temps partiel).
    quota_conges = db.Column(db.Integer, nullable=True)

    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    poste = db.relationship("Poste")
    projet = db.relationship("Projet")
    remunerations = db.relationship(
        "RemunerationSalarie", back_populates="salarie", order_by="RemunerationSalarie.date_versement.desc()"
    )
    absences = db.relationship(
        "Absence", back_populates="salarie", order_by="Absence.date_debut.desc()"
    )

    @property
    def solde_du(self):
        """Ce qu'Akiba doit encore à ce salarié (positif) ou ce qu'il doit
        (négatif, ex. avance pas encore rattrapée par le salaire) — calculé
        uniquement à partir des lignes de rémunération enregistrées, jamais
        deviné à partir du temps écoulé :
        - une ligne "non versée" (aucun moyen de paiement) est une dette
          déclarée envers le salarié : elle augmente le solde ;
        - une ligne versée (moyen de paiement renseigné) est un paiement
          réel, quel que soit son type (salaire, avance, prime) : elle
          réduit le solde, et peut le faire passer en négatif (avance) ;
        - une retenue réduit toujours le solde, versée ou non.
        """
        total = 0
        for r in self.remunerations:
            if r.type_remuneration == "retenue":
                total -= r.montant
            elif r.moyen_paiement_id is None:
                total += r.montant
            else:
                total -= r.montant
        return total

    def jours_conge_paye_pris(self, annee):
        """Nombre de jours de congé payé pris sur l'année donnée (une
        absence à cheval sur deux années ne compte que la part dans
        `annee`) — sert à comparer au quota annuel sur la fiche."""
        total = 0
        for a in self.absences:
            if a.type_absence != "conge_paye":
                continue
            debut = max(a.date_debut, a.date_debut.replace(year=annee, month=1, day=1))
            fin = min(a.date_fin, a.date_fin.replace(year=annee, month=12, day=31))
            if debut.year == annee and fin.year == annee and debut <= fin:
                total += (fin - debut).days + 1
        return total

    def __repr__(self):
        return f"<Salarie {self.nom}>"


class ParametresRH(db.Model):
    """Réglages RH globaux (ligne unique, id=1) — modifiables en
    Administration, appliqués comme valeur par défaut aux nouvelles fiches
    salarié sans écraser celles déjà personnalisées."""

    __tablename__ = "parametres_rh"

    id = db.Column(db.Integer, primary_key=True)
    quota_conges_defaut = db.Column(db.Integer, nullable=False, default=18)

    @classmethod
    def get(cls):
        parametres = db.session.get(cls, 1)
        if parametres is None:
            parametres = cls(id=1, quota_conges_defaut=18)
            db.session.add(parametres)
            db.session.commit()
        return parametres


class RemunerationSalarie(db.Model):
    """Salaire, avance, prime ou retenue versée à un salarié. §5.4 spec."""

    __tablename__ = "remuneration_salarie"

    id = db.Column(db.Integer, primary_key=True)
    salarie_id = db.Column(db.Integer, db.ForeignKey("salarie.id"), nullable=False)

    type_remuneration = db.Column(db.String(30), nullable=False)
    montant = db.Column(db.Integer, nullable=False)
    date_versement = db.Column(db.Date, nullable=False)
    moyen_paiement_id = db.Column(db.Integer, db.ForeignKey("moyen_paiement.id"), nullable=True)
    observations = db.Column(db.Text, nullable=True)

    created_by_subprofile_id = db.Column(db.Integer, db.ForeignKey("sub_profile.id"), nullable=True)
    created_by_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    salarie = db.relationship("Salarie", back_populates="remunerations")
    moyen_paiement = db.relationship("MoyenPaiement")

    def __repr__(self):
        return f"<RemunerationSalarie {self.type_remuneration} {self.montant}>"


class Absence(db.Model):
    """Absence d'un salarié (maladie, congé...), notée sur sa fiche."""

    __tablename__ = "absence"

    id = db.Column(db.Integer, primary_key=True)
    salarie_id = db.Column(db.Integer, db.ForeignKey("salarie.id"), nullable=False)

    type_absence = db.Column(db.String(30), nullable=False)
    date_debut = db.Column(db.Date, nullable=False)
    date_fin = db.Column(db.Date, nullable=False)
    observations = db.Column(db.Text, nullable=True)

    created_by_subprofile_id = db.Column(db.Integer, db.ForeignKey("sub_profile.id"), nullable=True)
    created_by_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    salarie = db.relationship("Salarie", back_populates="absences")

    @property
    def nombre_jours(self):
        return (self.date_fin - self.date_debut).days + 1

    def __repr__(self):
        return f"<Absence {self.type_absence} {self.date_debut}>"
