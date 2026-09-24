from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from ..admin.backup_service import log_audit
from ..auth.decorators import permission_required
from ..caisse.services import calculer_theorique, get_open_session
from ..extensions import db
from ..models import (
    Categorie,
    Client,
    MoyenPaiement,
    Poste,
    Produit,
    Projet,
    SousCategorie,
    TauxChange,
    TicketAttente,
    TypeTarif,
    Vente,
)
from . import bp
from .services import VenteError, annuler_vente, corriger_vente, enregistrer_vente


@bp.route("/")
@permission_required("point_de_vente")
def index():
    session = get_open_session()
    if session is None:
        return redirect(url_for("caisse.ouverture"))

    # Un emballage (vendable_pdv=False) ne doit jamais apparaître à la vente —
    # ce sont des produits que la boutique utilise elle-même, pas des articles
    # proposés au client (§ demande packaging).
    produits = (
        Produit.query.filter_by(is_archived=False, vendable_pdv=True)
        .order_by(Produit.name)
        .all()
    )
    # Le poste reste une classification comptable (achats, produits, rapports)
    # mais n'est plus affiché ni utilisé pour filtrer au PDV (retour
    # utilisateur : navigation simplifiée). Seules les catégories qui
    # contiennent réellement au moins un produit vendable au PDV sont
    # proposées ici — un poste peut mélanger des catégories de vente
    # (ex. "Vanille") et des catégories purement comptables (ex.
    # "Salaires_boutique", jamais de produit) : filtrer par poste seul ne
    # suffirait pas à écarter ces dernières (retour utilisateur, revient sur
    # la décision initiale de tout mélanger sans filtre).
    categories_avec_produits = {p.categorie_id for p in produits}
    categories = (
        Categorie.query.filter(Categorie.is_archived.is_(False), Categorie.id.in_(categories_avec_produits))
        .order_by(Categorie.poste_id, Categorie.ordre, Categorie.name)
        .all()
    )
    type_tarifs = TypeTarif.query.filter_by(is_archived=False).order_by(TypeTarif.ordre).all()
    # Un moyen rattaché au Compte Akiba (pas au tiroir PDV) n'a rien à faire
    # ici : un client ne paie jamais "dans" le compte Akiba directement,
    # seul le tiroir physique reçoit ses paiements (retour utilisateur du
    # 08/08/2026).
    moyens_paiement = (
        MoyenPaiement.query.filter_by(is_archived=False, visible_pdv=True).order_by(MoyenPaiement.name).all()
    )
    clients = Client.query.filter_by(is_archived=False).order_by(Client.nom).all()

    # Dernières ventes de la session, affichées au PDV pour éviter une double
    # saisie (ex. après une hésitation ou un rafraîchissement de page) — §1.6 CDC v1.
    dernieres_ventes = (
        Vente.query.filter_by(caisse_session_id=session.id, statut="validee")
        .order_by(Vente.id.desc())
        .limit(5)
        .all()
    )

    def _prix_disponibles(produit):
        # prix_pour() gère déjà la priorité prix manuel > rabais en % calculé
        # sur le prix de référence (arrondi à la centaine supérieure) — on
        # l'utilise ici pour que le PDV propose bien tous les tarifs vraiment
        # disponibles, pas seulement ceux saisis à la main sur la fiche produit.
        prix = {}
        for tt in type_tarifs:
            montant = produit.prix_pour(tt.code)
            if montant is not None:
                prix[tt.code] = montant
        return prix

    # Raccourci "fiche produit" affiché sur chaque carte du PDV — réservé aux
    # profils ayant le droit "produits" (seul droit requis par la route
    # admin.produit_modifier elle-même, distinct du reste du panneau Admin)
    # pour ne jamais pointer vers un lien qui renverrait une 403.
    peut_modifier_produits = current_user.profile.has_permission("produits")

    produits_json = [
        {
            "id": p.id,
            "name": p.name,
            "categorie_id": p.categorie_id,
            "posteId": p.poste_id,
            "prixLibre": p.prix_libre,
            "stock_quantite": p.stock_quantite,
            "statut_stock": p.statut_stock,
            "prix": _prix_disponibles(p),
            "photoUrl": url_for("admin.produit_photo", produit_id=p.id) if p.photo_path else None,
            "codeBarres": p.code_barres,
            "editUrl": (
                url_for("admin.produit_modifier", produit_id=p.id, depuis="pdv")
                if peut_modifier_produits
                else None
            ),
        }
        for p in produits
    ]

    moyens_paiement = sorted(moyens_paiement, key=lambda m: (not m.is_default, m.name))

    return render_template(
        "pos/index.html",
        categories=categories,
        produits_json=produits_json,
        type_tarifs=type_tarifs,
        moyens_paiement=moyens_paiement,
        session=session,
        dernieres_ventes=dernieres_ventes,
        clients=clients,
        taux_change=TauxChange.get(),
        caisse_theorique=calculer_theorique(session)["theorique"],
    )


@bp.route("/vente", methods=["POST"])
@permission_required("point_de_vente")
def creer_vente():
    session = get_open_session()
    if session is None:
        return jsonify({"ok": False, "error": "Aucune session de caisse ouverte."}), 400

    data = request.get_json(silent=True) or {}
    try:
        vente = enregistrer_vente(data, session, current_user)
    except VenteError as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 400

    # Le ticket encaissé n'est plus "en attente" : on supprime son brouillon
    # côté serveur pour ne pas le laisser traîner dans la barre d'onglets.
    ticket_id = data.get("ticket_attente_id")
    if ticket_id:
        ticket = db.session.get(TicketAttente, ticket_id)
        if ticket is not None and ticket.caisse_session_id == session.id:
            db.session.delete(ticket)
            db.session.commit()

    return jsonify({"ok": True, "redirect": url_for("pos.recu", vente_id=vente.id, fresh=1)})


def _ticket_to_dict(ticket):
    return {
        "id": ticket.id,
        "nom": ticket.nom,
        "typeTarifId": ticket.type_tarif_id,
        "clientId": ticket.client_id,
        "clientNom": ticket.client_nom,
        "lignes": ticket.lignes,
        "updatedAt": ticket.updated_at.isoformat(),
    }


@bp.route("/tickets")
@permission_required("point_de_vente")
def tickets_liste():
    session = get_open_session()
    if session is None:
        return jsonify({"ok": False, "error": "Aucune session de caisse ouverte."}), 400

    tickets = (
        TicketAttente.query.filter_by(caisse_session_id=session.id)
        .order_by(TicketAttente.created_at)
        .all()
    )
    return jsonify({"ok": True, "tickets": [_ticket_to_dict(t) for t in tickets]})


def _appliquer_donnees_ticket(ticket, data):
    ticket.nom = (data.get("nom") or "Ticket").strip()[:80] or "Ticket"
    ticket.type_tarif_id = data.get("type_tarif_id") or None
    ticket.client_id = data.get("client_id") or None
    ticket.client_nom = (data.get("client_nom") or "").strip() or None
    ticket.lignes = data.get("lignes") or []


@bp.route("/tickets", methods=["POST"])
@permission_required("point_de_vente")
def ticket_creer():
    session = get_open_session()
    if session is None:
        return jsonify({"ok": False, "error": "Aucune session de caisse ouverte."}), 400

    data = request.get_json(silent=True) or {}
    ticket = TicketAttente(
        caisse_session_id=session.id,
        created_by_subprofile_id=current_user.id,
        created_by_name=current_user.full_name,
    )
    _appliquer_donnees_ticket(ticket, data)
    db.session.add(ticket)
    db.session.commit()
    return jsonify({"ok": True, "ticket": _ticket_to_dict(ticket)})


@bp.route("/tickets/<int:ticket_id>", methods=["POST"])
@permission_required("point_de_vente")
def ticket_enregistrer(ticket_id):
    session = get_open_session()
    if session is None:
        return jsonify({"ok": False, "error": "Aucune session de caisse ouverte."}), 400

    ticket = db.session.get(TicketAttente, ticket_id)
    if ticket is None or ticket.caisse_session_id != session.id:
        abort(404)

    data = request.get_json(silent=True) or {}
    _appliquer_donnees_ticket(ticket, data)
    db.session.commit()
    return jsonify({"ok": True, "ticket": _ticket_to_dict(ticket)})


@bp.route("/tickets/<int:ticket_id>/supprimer", methods=["POST"])
@permission_required("point_de_vente")
def ticket_supprimer(ticket_id):
    session = get_open_session()
    if session is None:
        return jsonify({"ok": False, "error": "Aucune session de caisse ouverte."}), 400

    ticket = db.session.get(TicketAttente, ticket_id)
    if ticket is None or ticket.caisse_session_id != session.id:
        abort(404)

    db.session.delete(ticket)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/vente/<int:vente_id>")
@permission_required("point_de_vente")
def recu(vente_id):
    vente = db.session.get(Vente, vente_id)
    if vente is None:
        abort(404)
    # "fresh=1" : on arrive juste après la validation de la vente -> on propose
    # le choix "client suivant / terminer la session" (pas lors d'une simple
    # consultation ultérieure du reçu).
    fresh = request.args.get("fresh") == "1"
    return render_template("pos/recu.html", vente=vente, fresh=fresh)


@bp.route("/vente/<int:vente_id>/annuler", methods=["POST"])
@permission_required("corrections")
def vente_annuler(vente_id):
    vente = db.session.get(Vente, vente_id)
    if vente is None:
        abort(404)

    motif = (request.form.get("motif") or "").strip()
    try:
        annuler_vente(vente, motif, current_user)
    except VenteError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("pos.recu", vente_id=vente.id))

    log_audit(current_app, "vente_annulee", f"Vente #{vente.id} — {motif}", current_user)
    flash("Vente annulée : stock et comptes financiers ont été rétablis.", "info")
    return redirect(url_for("pos.recu", vente_id=vente.id))


def _vente_modifier_contexte(vente):
    return {
        "vente": vente,
        "postes": Poste.query.filter_by(is_archived=False).order_by(Poste.name).all(),
        "projets": Projet.query.filter_by(is_archived=False).order_by(Projet.name).all(),
        "categories": Categorie.query.filter_by(is_archived=False).order_by(Categorie.name).all(),
        "sous_categories": SousCategorie.query.filter_by(is_archived=False).order_by(SousCategorie.name).all(),
        "clients": Client.query.filter_by(is_archived=False).order_by(Client.nom).all(),
        "produits": Produit.query.filter_by(is_archived=False, vendable_pdv=True).order_by(Produit.name).all(),
        "moyens_paiement": MoyenPaiement.query.filter_by(is_archived=False).order_by(MoyenPaiement.name).all(),
    }


@bp.route("/vente/<int:vente_id>/modifier", methods=["GET", "POST"])
@permission_required("corrections")
def vente_modifier(vente_id):
    """Corrige une vente déjà validée : classement comptable, client,
    lignes (quantité, ajout, suppression) et moyen(s) de paiement — un motif
    est obligatoire dès que la correction touche à autre chose que le simple
    classement (voir corriger_vente(), le point le plus fréquent restant une
    erreur de moyen de paiement). L'annulation (vente_annuler) reste la seule
    option si la vente doit disparaître entièrement."""
    vente = db.session.get(Vente, vente_id)
    if vente is None:
        abort(404)
    if vente.statut != "validee":
        flash("Cette vente est annulée — elle ne peut plus être corrigée.", "error")
        return redirect(url_for("pos.recu", vente_id=vente.id))

    if request.method == "POST":
        lignes_data = {}
        for ligne in vente.lignes:
            quantite = request.form.get(f"quantite_{ligne.id}", type=int)
            if quantite is not None:
                lignes_data[ligne.id] = {"quantite": quantite}

        nouvelle_ligne_data = None
        nouveau_produit_id = request.form.get("nouveau_produit_id", type=int)
        if nouveau_produit_id:
            nouvelle_ligne_data = {
                "produit_id": nouveau_produit_id,
                "quantite": request.form.get("nouvelle_quantite", type=int),
                "prix_unitaire": request.form.get("nouveau_prix_unitaire", type=int),
            }

        paiements_data = []
        for moyen_id, montant in zip(
            request.form.getlist("paiement_moyen_paiement_id"), request.form.getlist("paiement_montant")
        ):
            paiements_data.append({"moyen_paiement_id": int(moyen_id) if moyen_id else None, "montant": montant})

        data = {
            "client_id": request.form.get("client_id", type=int),
            "client_nom": request.form.get("client_nom"),
            "commentaire": request.form.get("commentaire"),
            "lignes": lignes_data,
            "nouvelle_ligne": nouvelle_ligne_data,
            "paiements": paiements_data,
            "a_credit": bool(request.form.get("a_credit")),
        }
        motif = (request.form.get("motif") or "").strip()

        try:
            corriger_vente(vente, data, motif, current_user)
        except VenteError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return render_template("pos/vente_modifier.html", **_vente_modifier_contexte(vente))

        for ligne in vente.lignes:
            poste_id = request.form.get(f"poste_id_{ligne.id}", type=int)
            categorie_id = request.form.get(f"categorie_id_{ligne.id}", type=int)
            sous_categorie_id = request.form.get(f"sous_categorie_id_{ligne.id}", type=int)
            projet_id = request.form.get(f"projet_id_{ligne.id}", type=int)

            if poste_id and db.session.get(Poste, poste_id) is not None:
                ligne.poste_id = poste_id
            if categorie_id and db.session.get(Categorie, categorie_id) is not None:
                ligne.categorie_id = categorie_id
            ligne.sous_categorie_id = sous_categorie_id if sous_categorie_id else None
            ligne.projet_id = projet_id if projet_id else None

        log_audit(current_app, "vente_corrigee", f"Vente #{vente.id} — {motif}", current_user)
        db.session.commit()
        flash("Vente corrigée.", "info")
        return redirect(url_for("pos.recu", vente_id=vente.id))

    return render_template("pos/vente_modifier.html", **_vente_modifier_contexte(vente))
