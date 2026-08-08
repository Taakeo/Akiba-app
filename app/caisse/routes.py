from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..auth.decorators import permission_required
from ..extensions import db
from ..models import (
    Achat,
    CaisseSession,
    CompteFinancier,
    MoyenPaiement,
    MouvementCaisse,
    TauxChange,
    Vente,
    moyen_paiement_par_defaut,
)
from ..models.finance import utcnow
from . import bp
from .forms import FermetureCaisseForm, MouvementCaisseForm, OuvertureCaisseForm, TauxChangeCaisseForm
from .services import (
    achats_de_la_session,
    calculer_theorique,
    crediter_compte,
    debiter_compte,
    get_caisse_compte,
    get_compte_akiba,
    get_open_session,
    resume_session_par_moyen,
    tenter_ouverture_tiroir,
)


@bp.route("/")
@permission_required("caisse")
def status():
    """Comptes — vue Akiba globale (tous les comptes financiers), en lecture
    seule. La caisse physique du PDV (ouverture/clôture/entrée-sortie) se
    gère depuis Point de Vente > Caisse, pas ici — deux choses différentes :
    ceci couvre l'association entière, l'autre un seul poste de vente."""
    comptes = CompteFinancier.query.filter_by(is_archived=False).order_by(CompteFinancier.name).all()
    taux = TauxChange.get()
    taux_form = TauxChangeCaisseForm(obj=taux)
    return render_template("caisse/status.html", comptes=comptes, taux=taux, taux_form=taux_form)


@bp.route("/taux-change", methods=["POST"])
@permission_required("caisse")
def taux_change():
    taux = TauxChange.get()
    form = TauxChangeCaisseForm()
    if form.validate_on_submit():
        taux.ariary_pour_un_euro = form.ariary_pour_un_euro.data
        taux.updated_by_name = current_user.full_name
        db.session.commit()
        flash("Taux de change mis à jour.", "info")
    else:
        flash("Taux invalide.", "error")
    return redirect(url_for("caisse.status"))


def _construire_evenements_session(session):
    # "Transactions et tickets" de la session : tout ce qui s'y est passé
    # (ventes, mouvements manuels, achats — quel que soit leur moyen de
    # paiement), dans un seul journal chronologique cliquable. Le tri se
    # fait sur le vrai datetime (`moment`), pas sur le texte déjà formaté —
    # un tri sur chaîne "JJ/MM HH:MM" mélange l'ordre dès qu'on change de
    # mois (ex. "01/09" < "30/08" lexicographiquement).
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
    events.sort(key=lambda e: e["moment"], reverse=True)
    return events


@bp.route("/pdv")
@permission_required("caisse")
def pdv():
    """Caisse du Point de Vente — session en cours, ouverture/clôture,
    entrées-sorties. Propre à ce poste de vente, distinct de "Comptes"
    (vue Akiba globale)."""
    session = get_open_session()
    theorique = None
    events = []
    resume_moyens = []
    if session:
        theorique = calculer_theorique(session)
        events = _construire_evenements_session(session)
        resume_moyens = resume_session_par_moyen(session)

    return render_template(
        "caisse/pdv.html", session=session, theorique=theorique, events=events, resume_moyens=resume_moyens
    )


@bp.route("/ouverture", methods=["GET", "POST"])
@permission_required("caisse")
def ouverture():
    if get_open_session():
        flash("Une session de caisse est déjà ouverte.", "info")
        return redirect(url_for("caisse.pdv"))

    compte = get_caisse_compte()
    if compte is None:
        flash("Aucun compte de caisse physique configuré (is_caisse_physique).", "error")
        return redirect(url_for("caisse.pdv"))

    # Ce qui restait physiquement dans le tiroir à la précédente clôture
    # (compté réel moins ce qui a été prélevé vers le Compte Akiba) sert de
    # suggestion pour le fond d'ouverture — sans forcer, la réalité peut
    # différer (retour utilisateur du 08/08/2026).
    derniere_session = (
        CaisseSession.query.filter_by(statut="fermee", compte_financier_id=compte.id)
        .order_by(CaisseSession.fermee_le.desc())
        .first()
    )
    reliquat = None
    if derniere_session is not None and derniere_session.fond_reel is not None:
        reliquat = derniere_session.fond_reel - (derniere_session.montant_preleve or 0)

    form = OuvertureCaisseForm()
    if request.method == "GET" and reliquat is not None:
        form.fond_ouverture.data = reliquat

    if form.validate_on_submit():
        session = CaisseSession(
            compte_financier_id=compte.id,
            fond_ouverture=form.fond_ouverture.data,
            ouverte_par_id=current_user.id,
            ouverte_par_nom=current_user.full_name,
        )
        db.session.add(session)
        db.session.commit()
        flash("Caisse ouverte.", "info")
        return redirect(url_for("caisse.pdv"))

    return render_template("caisse/ouverture.html", form=form, compte=compte, reliquat=reliquat)


@bp.route("/fermeture", methods=["GET", "POST"])
@permission_required("caisse")
def fermeture():
    session = get_open_session()
    if session is None:
        flash("Aucune session de caisse ouverte.", "error")
        return redirect(url_for("caisse.pdv"))

    resume = calculer_theorique(session)
    compte_akiba = get_compte_akiba()
    form = FermetureCaisseForm()
    if request.method == "GET":
        # Suggestion par défaut : tout ce qui est compté part vers le Compte
        # Akiba (cas le plus fréquent) — modifiable si une partie doit
        # rester dans le tiroir.
        form.montant_preleve.data = 0

    if form.validate_on_submit():
        if form.montant_preleve.data > form.fond_reel.data:
            flash("Le montant prélevé ne peut pas dépasser le contenu réel compté.", "error")
            return render_template("caisse/fermeture.html", form=form, session=session, resume=resume, compte_akiba=compte_akiba)

        session.statut = "fermee"
        session.fond_theorique = resume["theorique"]
        session.fond_reel = form.fond_reel.data
        session.ecart = form.fond_reel.data - resume["theorique"]
        session.montant_preleve = form.montant_preleve.data
        session.commentaire_fermeture = form.commentaire.data
        session.fermee_par_id = current_user.id
        session.fermee_par_nom = current_user.full_name
        session.fermee_le = utcnow()

        # L'argent du PDV ne met à jour le Compte Akiba qu'à cet instant,
        # jamais avant (retour utilisateur du 08/08/2026) — les ventes et
        # achats de la session n'ont jamais touché le solde d'un compte
        # financier autre que le tiroir physique lui-même.
        if form.montant_preleve.data > 0:
            if compte_akiba is None:
                flash(
                    "Aucun Compte Akiba configuré (is_compte_akiba) : le montant prélevé n'a pas pu être "
                    "déposé. Configurez-le en Administration > Comptes financiers.",
                    "error",
                )
            else:
                debiter_compte(session.compte_financier, form.montant_preleve.data)
                crediter_compte(compte_akiba, form.montant_preleve.data)

        db.session.commit()
        flash("Caisse clôturée.", "info")
        return redirect(url_for("caisse.pdv"))

    return render_template("caisse/fermeture.html", form=form, session=session, resume=resume, compte_akiba=compte_akiba)


@bp.route("/mouvement", methods=["GET", "POST"])
@permission_required("caisse")
def mouvement():
    session = get_open_session()
    if session is None:
        flash("Ouvrez la caisse avant d'enregistrer un mouvement.", "error")
        return redirect(url_for("caisse.pdv"))

    moyens = MoyenPaiement.query.filter_by(is_archived=False).order_by(MoyenPaiement.name).all()

    form = MouvementCaisseForm()
    # Compte en suffixe : deux moyens peuvent porter le même nom mais
    # pointer vers des comptes différents (retour utilisateur du 08/08/2026).
    form.moyen_paiement_id.choices = [(m.id, f"{m.name} — {m.compte_financier.name}") for m in moyens]
    if request.method == "GET":
        defaut = moyen_paiement_par_defaut()
        if defaut:
            form.moyen_paiement_id.data = defaut.id
            form.origine.data = "pdv" if defaut.compte_financier.is_caisse_physique else "coffre_fort"

    if form.validate_on_submit():
        moyen = db.session.get(MoyenPaiement, form.moyen_paiement_id.data)
        # Garde-fou serveur, pas seulement visuel côté formulaire : le moyen
        # choisi doit correspondre à l'origine déclarée (Caisse PDV = compte
        # physique, Coffre-fort = tout le reste) — évite qu'un mouvement
        # atterrisse sur le mauvais compte sans que personne s'en aperçoive.
        origine_attendue = "pdv" if moyen.compte_financier.is_caisse_physique else "coffre_fort"
        if form.origine.data != origine_attendue:
            flash(
                f"« {moyen.name} » ne correspond pas à l'origine choisie "
                f"({'Caisse PDV' if form.origine.data == 'pdv' else 'Compte Akiba (coffre-fort)'}).",
                "error",
            )
            return render_template("caisse/mouvement.html", form=form, moyens=moyens)

        mouvement = MouvementCaisse(
            caisse_session_id=session.id,
            type_mouvement=form.type_mouvement.data,
            montant=form.montant.data,
            moyen_paiement_id=moyen.id,
            motif=form.motif.data,
            created_by_subprofile_id=current_user.id,
            created_by_name=current_user.full_name,
        )
        db.session.add(mouvement)

        if form.type_mouvement.data == "entree":
            crediter_compte(moyen.compte_financier, form.montant.data)
        else:
            debiter_compte(moyen.compte_financier, form.montant.data)

        db.session.commit()

        if moyen.ouvre_tiroir:
            tenter_ouverture_tiroir()
        flash("Mouvement de caisse enregistré.", "info")
        return redirect(url_for("caisse.pdv"))

    return render_template("caisse/mouvement.html", form=form, moyens=moyens)
