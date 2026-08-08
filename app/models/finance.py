from datetime import datetime, timezone

from ..extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class CompteFinancier(db.Model):
    """Où l'argent atterrit (caisse, mobile money, banque...). §7.4 spec."""

    __tablename__ = "compte_financier"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    devise = db.Column(db.String(10), nullable=False, default="Ar")
    solde = db.Column(db.Integer, nullable=False, default=0)
    is_caisse_physique = db.Column(db.Boolean, nullable=False, default=False)
    # Compte cible du prélèvement effectué à chaque clôture de caisse (§
    # amélioration : l'argent du PDV ne met à jour ce compte qu'à la
    # clôture, jamais avant — retour utilisateur du 08/08/2026). Un seul
    # compte porte ce rôle, comme is_caisse_physique pour le tiroir.
    is_compte_akiba = db.Column(db.Boolean, nullable=False, default=False)
    # Visibilité indépendante de l'archivage : un compte peut rester actif
    # pour les transactions mais être masqué du bloc "Comptes" du tableau de
    # bord (retour utilisateur du 08/08/2026 : ex. masquer Espèces Euro ou
    # BMOI de ce résumé sans les rendre inutilisables ailleurs).
    visible_tableau_bord = db.Column(db.Boolean, nullable=False, default=True)
    ordre_tableau_bord = db.Column(db.Integer, nullable=False, default=0)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    def __repr__(self):
        return f"<CompteFinancier {self.name}>"


class AjustementCompte(db.Model):
    """Correction manuelle du solde d'un compte financier par un
    administrateur (§ amélioration : renseigner les soldes réels actuels
    d'une association qui ne démarre pas de zéro). Toujours tracé — jamais
    une simple modification silencieuse du solde — même principe qu'un
    inventaire pour le stock : on ne corrige jamais sans motif ni preuve de
    qui a fait quoi et quand."""

    __tablename__ = "ajustement_compte"

    id = db.Column(db.Integer, primary_key=True)
    compte_financier_id = db.Column(db.Integer, db.ForeignKey("compte_financier.id"), nullable=False)
    ancien_solde = db.Column(db.Integer, nullable=False)
    nouveau_solde = db.Column(db.Integer, nullable=False)
    motif = db.Column(db.Text, nullable=False)

    created_by_subprofile_id = db.Column(db.Integer, db.ForeignKey("sub_profile.id"), nullable=True)
    created_by_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    compte_financier = db.relationship("CompteFinancier")

    @property
    def ecart(self):
        return self.nouveau_solde - self.ancien_solde

    def __repr__(self):
        return f"<AjustementCompte {self.compte_financier_id} {self.ancien_solde}->{self.nouveau_solde}>"


# Widgets connus du tableau de bord (§12 spec) — l'administrateur peut
# activer/désactiver et réordonner chacun depuis Administration, mais la
# LISTE des widgets possibles reste définie dans le code (pas de widget
# arbitraire créé par l'utilisateur, seulement du paramétrage sur ceux
# déjà programmés). Le droit d'accès sous-jacent (ex. "stocks" pour voir le
# widget Stocks) reste toujours vérifié en plus de ce réglage — désactiver
# un widget le cache pour tout le monde, l'activer ne donne aucun droit
# supplémentaire à qui ne l'avait pas déjà.
WIDGETS_TABLEAU_BORD = [
    ("activite", "Activité (CA du jour/mois, ventes)"),
    ("stocks", "Stocks (ruptures, valeur)"),
    ("comptes", "Comptes (soldes financiers)"),
    ("top_produits", "Produits les plus vendus"),
    ("alertes", "Alertes (stock, crédits clients, inventaires)"),
]


class WidgetTableauBord(db.Model):
    __tablename__ = "widget_tableau_bord"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    ordre = db.Column(db.Integer, nullable=False, default=0)
    actif = db.Column(db.Boolean, nullable=False, default=True)

    @classmethod
    def liste_ordonnee(cls):
        """Garantit qu'une ligne existe pour chaque widget connu (créée au
        premier accès, activée par défaut) puis retourne la liste triée par
        ordre d'affichage — jamais besoin d'un seed manuel séparé."""
        existants = {w.code: w for w in cls.query.all()}
        ordre_suivant = max([w.ordre for w in existants.values()], default=-1) + 1
        for code, _ in WIDGETS_TABLEAU_BORD:
            if code not in existants:
                nouveau = cls(code=code, ordre=ordre_suivant, actif=True)
                db.session.add(nouveau)
                existants[code] = nouveau
                ordre_suivant += 1
        db.session.commit()
        return sorted(existants.values(), key=lambda w: w.ordre)


class MoyenPaiement(db.Model):
    """Ce que le client utilise pour payer, rattaché au compte où l'argent atterrit. §7.4 spec.

    Deux moyens peuvent porter le même nom (ex. "Espèces Ariary" pour la
    caisse PDV ET pour le Compte Akiba) tant qu'ils ne pointent pas vers le
    même compte — d'où l'unicité sur (name, compte_financier_id) et non plus
    sur name seul (retour utilisateur du 08/08/2026 : ne jamais confondre
    deux moyens de même nom mais de provenance différente)."""

    __tablename__ = "moyen_paiement"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    compte_financier_id = db.Column(db.Integer, db.ForeignKey("compte_financier.id"), nullable=False)
    ouvre_tiroir = db.Column(db.Boolean, nullable=False, default=False)
    # Présélectionné dans tous les menus de moyen de paiement — en pratique
    # presque toujours "Espèces Ariary" (§ retour utilisateur : 99% des
    # paiements sont en espèces ariary).
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    # Un moyen rattaché au Compte Akiba (pas au tiroir PDV) n'a rien à faire
    # dans la modale d'encaissement du PDV — un client ne paie jamais
    # directement "dans" le compte Akiba, seul le tiroir physique reçoit ses
    # paiements. Reste utilisable pour les achats et mouvements de caisse.
    visible_pdv = db.Column(db.Boolean, nullable=False, default=True)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)

    compte_financier = db.relationship("CompteFinancier")

    __table_args__ = (db.UniqueConstraint("name", "compte_financier_id"),)

    def __repr__(self):
        return f"<MoyenPaiement {self.name}>"


class TauxChange(db.Model):
    """Taux de change Ariary/Euro (ligne unique, id=1), modifiable depuis le
    PDV ou l'Administration — sert uniquement d'aide au calcul pour un
    paiement en euros (affichage), les prix et la comptabilité restent
    toujours en ariary (§ jamais de décimal, une seule devise de référence)."""

    __tablename__ = "taux_change"

    id = db.Column(db.Integer, primary_key=True)
    ariary_pour_un_euro = db.Column(db.Integer, nullable=False, default=4800)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_by_name = db.Column(db.String(120), nullable=True)

    @classmethod
    def get(cls):
        taux = db.session.get(cls, 1)
        if taux is None:
            taux = cls(id=1, ariary_pour_un_euro=4800)
            db.session.add(taux)
            db.session.commit()
        return taux


class ParametresLegaux(db.Model):
    """Coordonnées légales d'Akiba (ligne unique, id=1), saisies une fois en
    Administration puis reprises telles quelles sur chaque facture officielle
    émise (§ amélioration facturation). Champs facultatifs à l'exception du
    nom : une association peut ne pas avoir de NIF/STAT à ses débuts, la
    facture reste émettable, seulement incomplète sur ces mentions."""

    __tablename__ = "parametres_legaux"

    id = db.Column(db.Integer, primary_key=True)
    raison_sociale = db.Column(db.String(200), nullable=False, default="AKIBA")
    adresse = db.Column(db.Text, nullable=True)
    telephone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    nif = db.Column(db.String(50), nullable=True)
    stat = db.Column(db.String(50), nullable=True)
    rcs = db.Column(db.String(50), nullable=True)

    @classmethod
    def get(cls):
        parametres = db.session.get(cls, 1)
        if parametres is None:
            parametres = cls(id=1)
            db.session.add(parametres)
            db.session.commit()
        return parametres


class ParametresImprimante(db.Model):
    """Nom de l'imprimante Windows utilisée pour ouvrir le tiroir-caisse hors
    vente (§6.5, §7.5 spec) — ligne unique, id=1. Doit correspondre
    exactement au nom de l'imprimante tel qu'installée dans Windows
    (Paramètres > Imprimantes), pas au nom du modèle physique."""

    __tablename__ = "parametres_imprimante"

    id = db.Column(db.Integer, primary_key=True)
    nom_imprimante = db.Column(db.String(150), nullable=False, default="POS-80")

    @classmethod
    def get(cls):
        parametres = db.session.get(cls, 1)
        if parametres is None:
            parametres = cls(id=1)
            db.session.add(parametres)
            db.session.commit()
        return parametres


def moyen_paiement_par_defaut():
    """Le moyen de paiement à présélectionner par défaut dans les formulaires
    (celui marqué is_default, sinon le premier actif par ordre alphabétique)."""
    return (
        MoyenPaiement.query.filter_by(is_archived=False, is_default=True).first()
        or MoyenPaiement.query.filter_by(is_archived=False).order_by(MoyenPaiement.name).first()
    )


class CaisseSession(db.Model):
    """Session de caisse : ouverture (fond de caisse) / fermeture (écart). §7.2 spec.

    Mono-poste, une seule caisse (§2) : une seule session "ouverte" à la fois.
    """

    __tablename__ = "caisse_session"

    id = db.Column(db.Integer, primary_key=True)
    compte_financier_id = db.Column(db.Integer, db.ForeignKey("compte_financier.id"), nullable=False)

    statut = db.Column(db.String(20), nullable=False, default="ouverte")  # ouverte | fermee

    fond_ouverture = db.Column(db.Integer, nullable=False)
    ouverte_par_id = db.Column(db.Integer, db.ForeignKey("sub_profile.id"), nullable=True)
    ouverte_par_nom = db.Column(db.String(120), nullable=False)
    ouverte_le = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    fond_theorique = db.Column(db.Integer, nullable=True)
    fond_reel = db.Column(db.Integer, nullable=True)
    ecart = db.Column(db.Integer, nullable=True)
    # Ce qui est physiquement sorti du tiroir à la clôture pour rejoindre le
    # Compte Akiba — seul ce montant met à jour le solde du Compte Akiba,
    # jamais les ventes/mouvements individuels pendant la session (retour
    # utilisateur du 08/08/2026). Le reste (fond_reel - montant_preleve)
    # reste physiquement dans le tiroir et sert de suggestion pour le fond
    # d'ouverture de la session suivante.
    montant_preleve = db.Column(db.Integer, nullable=True)
    commentaire_fermeture = db.Column(db.Text, nullable=True)
    fermee_par_id = db.Column(db.Integer, db.ForeignKey("sub_profile.id"), nullable=True)
    fermee_par_nom = db.Column(db.String(120), nullable=True)
    fermee_le = db.Column(db.DateTime(timezone=True), nullable=True)

    compte_financier = db.relationship("CompteFinancier")
    mouvements = db.relationship("MouvementCaisse", back_populates="caisse_session")

    def __repr__(self):
        return f"<CaisseSession #{self.id} {self.statut}>"


class MouvementCaisse(db.Model):
    """Entrée / sortie de caisse manuelle (apport, retrait, dépense...). §7.3 spec."""

    __tablename__ = "mouvement_caisse"

    id = db.Column(db.Integer, primary_key=True)
    caisse_session_id = db.Column(db.Integer, db.ForeignKey("caisse_session.id"), nullable=False)
    type_mouvement = db.Column(db.String(10), nullable=False)  # entree | sortie
    montant = db.Column(db.Integer, nullable=False)
    moyen_paiement_id = db.Column(db.Integer, db.ForeignKey("moyen_paiement.id"), nullable=False)
    motif = db.Column(db.String(255), nullable=False)

    created_by_subprofile_id = db.Column(db.Integer, db.ForeignKey("sub_profile.id"), nullable=True)
    created_by_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    caisse_session = db.relationship("CaisseSession", back_populates="mouvements")
    moyen_paiement = db.relationship("MoyenPaiement")

    def __repr__(self):
        return f"<MouvementCaisse {self.type_mouvement} {self.montant}>"
