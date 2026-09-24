from flask import flash, url_for

from ..extensions import db
from ..models import (
    Achat,
    CaisseSession,
    CompteFinancier,
    MouvementCaisse,
    MoyenPaiement,
    ParametresImprimante,
    RemunerationSalarie,
    TauxChange,
    TYPES_REMUNERATION,
    Vente,
    VentePaiement,
)
from ..models.finance import utcnow
from .printer import ImprimanteError, ouvrir_tiroir

_LABELS_TYPE_REMUNERATION = dict(TYPES_REMUNERATION)


def montant_en_ariary(moyen, montant):
    """Convertit un montant saisi dans la devise d'un moyen de paiement vers
    son équivalent Ariary, seul référentiel de prix/solde de l'app (§7.6
    spec) — ex. un paiement ou remboursement en euros doit être comparé/
    déduit d'un total ariary via le taux de change, jamais traité comme si
    le nombre saisi était déjà en ariary. Le montant *crédité au compte*
    reste lui dans sa devise d'origine, voir les appelants."""
    devise = moyen.compte_financier.devise
    if devise == "Ar":
        return montant
    if devise == "€":
        taux = TauxChange.get().ariary_pour_un_euro
        return montant * taux
    # Autres devises éventuelles (non utilisées actuellement, §7.4 spec) :
    # pas de taux de change modélisé, on ne peut que supposer 1:1 plutôt que
    # de planter l'opération.
    return montant


def montant_devise_depuis_ariary(devise, montant_ariary):
    """Convertit un montant ariary vers une devise donnée — coeur de
    montant_depuis_ariary(), extrait à part pour les cas où le compte
    réellement crédité n'est pas celui du moyen de paiement choisi (ex.
    Ventes externes : toujours le Compte Akiba, quel que soit le moyen)."""
    if devise == "Ar":
        return montant_ariary
    if devise == "€":
        taux = TauxChange.get().ariary_pour_un_euro
        if taux <= 0:
            return montant_ariary
        return round(montant_ariary / taux)
    return montant_ariary


def montant_depuis_ariary(moyen, montant_ariary):
    """Inverse de montant_en_ariary() : convertit un montant ariary vers la
    devise du compte du moyen de paiement. Utile quand seul le coût ariary
    est saisi (ex. `Achat.montant_total`, toujours exprimé en ariary — c'est
    la vraie dépense, indépendante du moyen utilisé) mais que le compte
    réellement débité est dans une autre devise (payé en espèces euros) :
    le compte doit refléter ce qui en est réellement sorti, pas le montant
    ariary brut affublé du mauvais symbole monétaire."""
    return montant_devise_depuis_ariary(moyen.compte_financier.devise, montant_ariary)


def get_caisse_compte():
    """Le compte financier représentant le tiroir-caisse physique (mono-poste, §2 spec)."""
    return CompteFinancier.query.filter_by(is_caisse_physique=True, is_archived=False).first()


def get_compte_akiba():
    """Le compte financier cible du prélèvement effectué à chaque clôture de
    caisse (§ amélioration : l'argent du PDV ne l'alimente qu'à la
    clôture, jamais avant — retour utilisateur du 08/08/2026)."""
    return CompteFinancier.query.filter_by(is_compte_akiba=True, is_archived=False).first()


def tenter_ouverture_tiroir():
    """Envoie la commande d'ouverture du tiroir sans jamais bloquer
    l'opération en cours (mouvement de caisse ou achat déjà enregistré) : un
    problème d'imprimante ne doit pas empêcher de sauvegarder une entrée,
    une sortie d'argent ou un achat payé en espèces PDV — on prévient juste
    l'utilisateur si ça échoue. Partagé entre caisse/routes.py (mouvements)
    et achats/routes.py (achat payé depuis le tiroir PDV)."""
    try:
        ouvrir_tiroir(ParametresImprimante.get().nom_imprimante)
    except ImprimanteError as exc:
        flash(f"Enregistré, mais {str(exc)[0].lower()}{str(exc)[1:]}", "error")


def get_open_session():
    return CaisseSession.query.filter_by(statut="ouverte").order_by(CaisseSession.id.desc()).first()


def crediter_compte(compte, montant):
    compte.solde += montant


def debiter_compte(compte, montant):
    compte.solde -= montant


def enregistrer_paiement(compte, montant):
    """Applique un encaissement (vente ou entrée de caisse) au solde du compte."""
    crediter_compte(compte, montant)


def enregistrer_sortie(compte, montant):
    debiter_compte(compte, montant)


def calculer_theorique(session: CaisseSession):
    """Contenu théorique du tiroir : fond initial + encaissements espèces - sorties espèces
    de cette session, sur le compte physique de la caisse (§7.2 spec)."""
    compte_id = session.compte_financier_id

    encaissements_ventes = (
        db.session.query(db.func.coalesce(db.func.sum(VentePaiement.montant), 0))
        .join(VentePaiement.vente)
        .join(VentePaiement.moyen_paiement)
        .filter(
            # Une vente annulée (annuler_vente(), app/pos/services.py) reverse
            # déjà son impact sur le compte via debiter_compte — sans ce
            # filtre, son encaissement d'origine resterait compté ici en plus,
            # faussant le théorique malgré la correction.
            VentePaiement.vente.has(caisse_session_id=session.id, statut="validee"),
        )
        .filter(VentePaiement.moyen_paiement.has(compte_financier_id=compte_id))
        .scalar()
    )

    entrees = (
        db.session.query(db.func.coalesce(db.func.sum(MouvementCaisse.montant), 0))
        .filter(
            MouvementCaisse.caisse_session_id == session.id,
            MouvementCaisse.type_mouvement == "entree",
        )
        .join(MouvementCaisse.moyen_paiement)
        .filter(MouvementCaisse.moyen_paiement.has(compte_financier_id=compte_id))
        .scalar()
    )

    sorties = (
        db.session.query(db.func.coalesce(db.func.sum(MouvementCaisse.montant), 0))
        .filter(
            MouvementCaisse.caisse_session_id == session.id,
            MouvementCaisse.type_mouvement == "sortie",
        )
        .join(MouvementCaisse.moyen_paiement)
        .filter(MouvementCaisse.moyen_paiement.has(compte_financier_id=compte_id))
        .scalar()
    )

    # Achats (stock ou dépense) payés en espèces depuis cette même caisse
    # pendant la session — sans ça, le théorique restait surévalué et
    # provoquait un faux écart à la clôture dès qu'un achat était réglé
    # en cash depuis le tiroir. Un achat annulé (achats/routes.py::annuler)
    # recrédite déjà le compte séparément — sans ce filtre, il resterait
    # compté ici en plus, faussant le théorique malgré la correction (même
    # principe que le filtre statut="validee" sur les ventes ci-dessus).
    achats_especes = (
        db.session.query(db.func.coalesce(db.func.sum(Achat.montant_total), 0))
        .filter(Achat.caisse_session_id == session.id, Achat.is_annule.is_(False))
        .join(Achat.moyen_paiement)
        .filter(Achat.moyen_paiement.has(compte_financier_id=compte_id))
        .scalar()
    )

    # Versements RH (salaire, avance, prime, retenue) payés en espèces depuis
    # cette même caisse pendant la session — même principe que achats_especes
    # ci-dessus : sans ça, une avance donnée en cash au tiroir n'était jamais
    # déduite du théorique, créant un faux écart à la clôture (retour
    # utilisateur). Un versement annulé (rh/routes.py::annuler_remuneration)
    # recrédite déjà le compte séparément — même filtre is_annule que pour un
    # achat annulé.
    remunerations_especes = (
        db.session.query(db.func.coalesce(db.func.sum(RemunerationSalarie.montant), 0))
        .filter(RemunerationSalarie.caisse_session_id == session.id, RemunerationSalarie.is_annule.is_(False))
        .join(RemunerationSalarie.moyen_paiement)
        .filter(RemunerationSalarie.moyen_paiement.has(compte_financier_id=compte_id))
        .scalar()
    )

    recettes = encaissements_ventes + entrees
    depenses = sorties + achats_especes + remunerations_especes
    return {
        "recettes": recettes,
        "depenses": depenses,
        "theorique": session.fond_ouverture + recettes - depenses,
    }


def achats_de_la_session(session):
    """Achats à imputer à cette session pour le résumé/reporting par moyen de
    paiement — pas utilisé pour le calcul de l'écart de clôture, qui reste
    strictement basé sur `caisse_session_id` (voir calculer_theorique). Un
    achat payé en espèces depuis la caisse physique y est déjà rattaché,
    mais un achat payé par un autre moyen (mobile money, banque) pendant la
    session ne l'est jamais (§ modèle Achat, volontairement) — on le
    retrouve ici via son horodatage, pour que le résumé de session reflète
    tout ce qui a été dépensé pendant ce service, quel que soit le moyen."""
    fin = session.fermee_le or utcnow()
    return Achat.query.filter(
        Achat.is_annule.is_(False),
        db.or_(
            Achat.caisse_session_id == session.id,
            db.and_(Achat.created_at >= session.ouverte_le, Achat.created_at <= fin),
        ),
    ).all()


def remunerations_de_la_session(session):
    """Versements RH (salaire, avance, prime, retenue) à imputer à cette
    session pour le résumé/reporting par moyen de paiement — même principe
    que achats_de_la_session() : un versement payé en espèces depuis la
    caisse physique y est déjà rattaché (caisse_session_id), un versement
    payé par un autre moyen pendant la session ne l'est jamais, on le
    retrouve ici via son horodatage."""
    fin = session.fermee_le or utcnow()
    return RemunerationSalarie.query.filter(
        RemunerationSalarie.is_annule.is_(False),
        RemunerationSalarie.moyen_paiement_id.isnot(None),
        db.or_(
            RemunerationSalarie.caisse_session_id == session.id,
            db.and_(RemunerationSalarie.created_at >= session.ouverte_le, RemunerationSalarie.created_at <= fin),
        ),
    ).all()


def resume_session_par_moyen(session):
    """Résumé/reporting (pas un solde physique) : pour chaque moyen de
    paiement actif, ce qui a été encaissé/décaissé pendant cette session —
    ventes + entrées/sorties de caisse + achats payés par ce moyen.
    Contrairement à calculer_theorique(), pas limité au compte physique :
    répond à "combien est rentré en Ariary, en Euro, en Orange Money...
    pendant ce service", que l'argent soit physiquement dans le tiroir ou
    sur un compte externe (§ amélioration PDV)."""
    achats_par_moyen = {}
    for achat in achats_de_la_session(session):
        achats_par_moyen[achat.moyen_paiement_id] = achats_par_moyen.get(achat.moyen_paiement_id, 0) + achat.montant_total

    remunerations_par_moyen = {}
    for remuneration in remunerations_de_la_session(session):
        remunerations_par_moyen[remuneration.moyen_paiement_id] = (
            remunerations_par_moyen.get(remuneration.moyen_paiement_id, 0) + remuneration.montant
        )

    moyens = MoyenPaiement.query.filter_by(is_archived=False).order_by(MoyenPaiement.name).all()
    resultats = []
    for moyen in moyens:
        encaissements_ventes = (
            db.session.query(db.func.coalesce(db.func.sum(VentePaiement.montant), 0))
            .join(VentePaiement.vente)
            .filter(
                VentePaiement.moyen_paiement_id == moyen.id,
                VentePaiement.vente.has(caisse_session_id=session.id, statut="validee"),
            )
            .scalar()
        )
        entrees = (
            db.session.query(db.func.coalesce(db.func.sum(MouvementCaisse.montant), 0))
            .filter(
                MouvementCaisse.caisse_session_id == session.id,
                MouvementCaisse.moyen_paiement_id == moyen.id,
                MouvementCaisse.type_mouvement == "entree",
            )
            .scalar()
        )
        sorties = (
            db.session.query(db.func.coalesce(db.func.sum(MouvementCaisse.montant), 0))
            .filter(
                MouvementCaisse.caisse_session_id == session.id,
                MouvementCaisse.moyen_paiement_id == moyen.id,
                MouvementCaisse.type_mouvement == "sortie",
            )
            .scalar()
        )
        achats_montant = achats_par_moyen.get(moyen.id, 0)
        remunerations_montant = remunerations_par_moyen.get(moyen.id, 0)

        # Le fond de caisse initial n'appartient qu'au compte physique sur
        # lequel la session a été ouverte — sans ça, ce tableau affichait un
        # total différent (plus bas) de celui du bloc "Théorique" juste
        # au-dessus, qui l'inclut bien (calculer_theorique), pour la même
        # ligne "Espèces Ariary" au même instant.
        fond_ouverture = session.fond_ouverture if moyen.compte_financier_id == session.compte_financier_id else 0

        resultats.append(
            {
                "moyen": moyen,
                "compte": moyen.compte_financier,
                "fond_ouverture": fond_ouverture,
                "encaissements_ventes": encaissements_ventes,
                "entrees": entrees,
                "sorties": sorties,
                "achats": achats_montant,
                "remunerations": remunerations_montant,
                "total": (
                    fond_ouverture + encaissements_ventes + entrees - sorties - achats_montant - remunerations_montant
                ),
            }
        )
    return resultats


def construire_evenements_session(session):
    """Journal chronologique de tout ce qui s'est passé pendant une session
    (ventes, mouvements manuels, achats) — utilisé à la fois par l'écran
    "Caisse PDV" (session en cours) et par le rapport de session, ouverte ou
    fermée (§ amélioration rapport de session de caisse). Le tri se fait sur
    le vrai datetime (`moment`), pas sur le texte déjà formaté — un tri sur
    chaîne "JJ/MM HH:MM" mélange l'ordre dès qu'on change de mois."""
    events = []
    for mouvement in session.mouvements:
        events.append(
            {
                "titre": mouvement.motif,
                "sous_titre": f"{mouvement.created_at:%d/%m %H:%M} — {mouvement.moyen_paiement.name} — par {mouvement.created_by_name}",
                "montant": mouvement.montant if mouvement.type_mouvement == "entree" else -mouvement.montant,
                "icon": "arrow_downward" if mouvement.type_mouvement == "entree" else "arrow_upward",
                "moment": mouvement.created_at,
                "lien": None,
            }
        )
    for vente in Vente.query.filter_by(caisse_session_id=session.id, statut="validee"):
        events.append(
            {
                "titre": f"Vente comptoir #{vente.id}",
                "sous_titre": f"{vente.created_at:%d/%m %H:%M} — par {vente.created_by_name}",
                "montant": vente.total,
                "icon": "point_of_sale",
                "moment": vente.created_at,
                "lien": url_for("pos.recu", vente_id=vente.id),
            }
        )
    for achat in achats_de_la_session(session):
        events.append(
            {
                "titre": achat.nom or (f"Achat #{achat.id}" if achat.type_achat == "stock" else "Dépense"),
                "sous_titre": f"{achat.created_at:%d/%m %H:%M} — {achat.moyen_paiement.name} — par {achat.created_by_name}",
                "montant": -achat.montant_total,
                "icon": "shopping_cart",
                "moment": achat.created_at,
                "lien": url_for("achats.modifier", achat_id=achat.id),
            }
        )
    for remuneration in remunerations_de_la_session(session):
        events.append(
            {
                "titre": f"{_LABELS_TYPE_REMUNERATION.get(remuneration.type_remuneration, remuneration.type_remuneration)} — {remuneration.salarie.nom}",
                "sous_titre": f"{remuneration.created_at:%d/%m %H:%M} — {remuneration.moyen_paiement.name} — par {remuneration.created_by_name}",
                "montant": -remuneration.montant,
                "icon": "badge",
                "moment": remuneration.created_at,
                "lien": url_for("rh.fiche", salarie_id=remuneration.salarie_id),
            }
        )
    events.sort(key=lambda e: e["moment"], reverse=True)
    return events


def corrections_de_la_session(session):
    """Ventes annulées, ventes corrigées et achats annulés rattachés à cette
    session — section "corrections" du rapport de session de caisse (§
    amélioration rapport de session de caisse) : distinct du journal
    chronologique normal (construire_evenements_session), qui n'affiche que
    les opérations encore valides."""
    corrections = []
    for vente in Vente.query.filter_by(caisse_session_id=session.id, statut="annulee"):
        moment = vente.annule_le or vente.created_at
        corrections.append(
            {
                "titre": f"Vente #{vente.id} annulée",
                "sous_titre": (
                    f"{moment:%d/%m %H:%M} — motif : {vente.annule_motif or '—'} — "
                    f"par {vente.annule_par_nom or vente.created_by_name}"
                ),
                "montant": -vente.total,
                "icon": "cancel",
                "moment": moment,
                "lien": url_for("pos.recu", vente_id=vente.id),
            }
        )
    for vente in Vente.query.filter(
        Vente.caisse_session_id == session.id,
        Vente.statut == "validee",
        Vente.derniere_correction_le.isnot(None),
    ):
        corrections.append(
            {
                "titre": f"Vente #{vente.id} corrigée",
                "sous_titre": (
                    f"{vente.derniere_correction_le:%d/%m %H:%M} — motif : {vente.derniere_correction_motif or '—'} — "
                    f"par {vente.derniere_correction_par_nom}"
                ),
                "montant": None,
                "icon": "edit",
                "moment": vente.derniere_correction_le,
                "lien": url_for("pos.recu", vente_id=vente.id),
            }
        )
    for achat in Achat.query.filter_by(caisse_session_id=session.id, is_annule=True):
        moment = achat.annule_le or achat.created_at
        corrections.append(
            {
                "titre": f"{achat.nom or ('Achat #' + str(achat.id))} annulé",
                "sous_titre": (
                    f"{moment:%d/%m %H:%M} — motif : {achat.annule_motif or '—'} — "
                    f"par {achat.annule_par_nom or achat.created_by_name}"
                ),
                "montant": achat.montant_total,
                "icon": "cancel",
                "moment": moment,
                "lien": url_for("achats.modifier", achat_id=achat.id),
            }
        )
    for remuneration in RemunerationSalarie.query.filter_by(caisse_session_id=session.id, is_annule=True):
        moment = remuneration.annule_le or remuneration.created_at
        label = _LABELS_TYPE_REMUNERATION.get(remuneration.type_remuneration, remuneration.type_remuneration)
        corrections.append(
            {
                "titre": f"{label} — {remuneration.salarie.nom} annulé(e)",
                "sous_titre": (
                    f"{moment:%d/%m %H:%M} — motif : {remuneration.annule_motif or '—'} — "
                    f"par {remuneration.annule_par_nom or remuneration.created_by_name}"
                ),
                "montant": remuneration.montant,
                "icon": "cancel",
                "moment": moment,
                "lien": url_for("rh.fiche", salarie_id=remuneration.salarie_id),
            }
        )
    corrections.sort(key=lambda e: e["moment"], reverse=True)
    return corrections
