from ..caisse.services import crediter_compte, debiter_compte
from ..extensions import db
from ..models import Client, LigneVente, MoyenPaiement, Produit, TypeTarif, Vente, VentePaiement, enregistrer_mouvement
from ..models.finance import utcnow


class VenteError(ValueError):
    pass


def enregistrer_vente(data, session, current_user):
    """Valide et enregistre une vente : prix recalculés serveur (jamais depuis le
    client), stock décrémenté, comptes financiers crédités — une seule saisie
    propage caisse + stock (§1, §6, §7.6 spec)."""

    type_tarif = db.session.get(TypeTarif, data.get("type_tarif_id"))
    if type_tarif is None or type_tarif.is_archived:
        raise VenteError("Tarif invalide.")

    lignes_data = data.get("lignes") or []
    if not lignes_data:
        raise VenteError("Le ticket est vide.")

    client = None
    client_id = data.get("client_id")
    if client_id:
        client = db.session.get(Client, client_id)
        if client is None or client.is_archived:
            raise VenteError("Client invalide.")

    vente = Vente(
        caisse_session_id=session.id,
        type_tarif_id=type_tarif.id,
        client_id=client.id if client else None,
        client_nom=client.nom if client else (data.get("client_nom") or "").strip() or None,
        commentaire=(data.get("commentaire") or "").strip() or None,
        created_by_subprofile_id=current_user.id,
        created_by_name=current_user.full_name,
    )
    db.session.add(vente)
    db.session.flush()  # attribue vente.id, référencé par les mouvements de stock

    sous_total = 0
    for ligne_data in lignes_data:
        produit = db.session.get(Produit, ligne_data.get("produit_id"))
        if produit is None or produit.is_archived:
            raise VenteError("Produit invalide.")

        quantite = int(ligne_data.get("quantite") or 0)
        if quantite < 1:
            raise VenteError(f"Quantité invalide pour {produit.name}.")

        offert = bool(ligne_data.get("offert"))
        remise = max(0, int(ligne_data.get("remise") or 0))

        # Un stock affiché à 0 (ou insuffisant) ne bloque plus la vente —
        # l'inventaire réel du magasin peut être en avance sur l'inventaire
        # saisi (retour utilisateur : refaire l'inventaire est la
        # responsabilité du vendeur, pas une raison de bloquer un client au
        # comptoir). enregistrer_mouvement() empêche que le stock affiché
        # passe sous zéro pour autant.

        if produit.prix_libre:
            # Prix libre (ex. Pourboire) : pas de tarif fixe, le montant vient
            # du panier — mais reste un entier positif, jamais négatif ou nul
            # (sauf article offert), pour ne pas fausser le total du ticket.
            prix_unitaire = int(ligne_data.get("prix_unitaire") or 0)
            if prix_unitaire <= 0 and not offert:
                raise VenteError(f"Montant invalide pour {produit.name}.")
        else:
            prix_unitaire = produit.prix_pour(type_tarif.code)
            if prix_unitaire is None:
                raise VenteError(f"Aucun tarif {type_tarif.label} pour {produit.name}.")

        ligne = LigneVente(
            produit_id=produit.id,
            produit_nom=produit.name,
            poste_id=produit.poste_id,
            projet_id=produit.projet_id,
            categorie_id=produit.categorie_id,
            sous_categorie_id=produit.sous_categorie_id,
            quantite=quantite,
            prix_unitaire=prix_unitaire,
            remise=remise,
            offert=offert,
            commentaire=(ligne_data.get("commentaire") or "").strip() or None,
        )
        ligne.calculer_total()
        sous_total += ligne.total_ligne
        if not produit.stock_illimite:
            # Un article offert est une sortie de stock distincte d'une vente
            # payée (§9.5 spec : "cadeaux/dégustations" à distinguer des
            # ventes pour affiner l'analyse des résultats).
            enregistrer_mouvement(
                produit,
                "sortie",
                "offert" if offert else "vente",
                quantite,
                current_user,
                reference_type="vente",
                reference_id=vente.id,
            )
        vente.lignes.append(ligne)

    remise_vente = max(0, int(data.get("remise_vente") or 0))
    total = max(0, sous_total - remise_vente)

    vente.sous_total = sous_total
    vente.remise = remise_vente
    vente.total = total

    paiements_data = data.get("paiements") or []
    a_credit = bool(data.get("a_credit"))
    if a_credit and client is None:
        raise VenteError("La vente à crédit nécessite un client enregistré.")

    if total > 0 and not paiements_data and not a_credit:
        raise VenteError("Aucun moyen de paiement renseigné.")

    total_paye = 0
    paiement_devise_etrangere = False
    for paiement_data in paiements_data:
        montant = int(paiement_data.get("montant") or 0)
        if montant <= 0:
            continue
        moyen = db.session.get(MoyenPaiement, paiement_data.get("moyen_paiement_id"))
        if moyen is None or moyen.is_archived:
            raise VenteError("Moyen de paiement invalide.")
        vente.paiements.append(VentePaiement(moyen_paiement_id=moyen.id, montant=montant))
        crediter_compte(moyen.compte_financier, montant)
        if moyen.compte_financier.devise == "Ar":
            total_paye += montant
        else:
            # Paiement en devise étrangère (ex. euros) : le montant saisi est
            # manuel et définitif, jamais recalculé/comparé au total ariary
            # via le taux de change (retour utilisateur : "c'est l'euro qui
            # doit être pris en compte", "plus de comparaison ariary-euro").
            # Un taux mal renseigné ou un prix négocié différent du calcul
            # théorique ne doit jamais bloquer la vente.
            paiement_devise_etrangere = True

    montant_restant = 0 if paiement_devise_etrangere else total - total_paye
    if montant_restant > 0:
        if not a_credit:
            raise VenteError(
                f"Le total payé ({total_paye}) ne correspond pas au total du ticket ({total})."
            )
        vente.montant_credit = montant_restant
        vente.credit_solde_restant = montant_restant
        client.solde_credit += montant_restant
    elif montant_restant < 0:
        raise VenteError(f"Le total payé ({total_paye}) dépasse le total du ticket ({total}).")

    db.session.commit()
    return vente


def annuler_vente(vente, motif, current_user):
    """Annule une vente déjà validée (ex. double saisie par erreur) : reverse
    proprement son impact stock + comptes financiers + crédit client, sans
    jamais supprimer les lignes/paiements d'origine (trace d'audit conservée
    — même esprit que AjustementCompte, jamais une correction silencieuse).
    Réservé au droit "corrections" (app/pos/routes.py)."""
    if vente.statut != "validee":
        raise VenteError("Cette vente est déjà annulée.")
    if vente.facture_id is not None:
        raise VenteError(
            "Cette vente est déjà facturée — elle ne peut pas être annulée directement."
        )
    if not motif or not motif.strip():
        raise VenteError("Un motif est obligatoire pour annuler une vente.")

    # Stock : chaque ligne ayant décrémenté un produit suivi (vente/offert,
    # jamais stock_illimite) reçoit un mouvement d'entrée inverse.
    for ligne in vente.lignes:
        produit = ligne.produit
        if produit is not None and not produit.stock_illimite:
            enregistrer_mouvement(
                produit,
                "entree",
                "correction",
                ligne.quantite,
                current_user,
                commentaire=f"Annulation vente #{vente.id}",
                reference_type="vente",
                reference_id=vente.id,
            )

    # Comptes financiers : chaque paiement encaissé est repris dans sa propre
    # devise, symétriquement à crediter_compte() lors de l'encaissement — les
    # lignes VentePaiement elles-mêmes restent en base (trace d'audit).
    for paiement in vente.paiements:
        debiter_compte(paiement.moyen_paiement.compte_financier, paiement.montant)

    # Crédit client : seulement s'il n'a pas déjà commencé à être remboursé —
    # un reversal FIFO partiel serait trop délicat à défaire automatiquement
    # sans risquer de désynchroniser d'autres ventes à crédit du même client.
    if vente.montant_credit > 0:
        if vente.credit_solde_restant < vente.montant_credit:
            raise VenteError(
                "Cette vente à crédit a déjà commencé à être remboursée — "
                "elle ne peut pas être annulée automatiquement."
            )
        if vente.client is not None:
            vente.client.solde_credit -= vente.credit_solde_restant
        vente.credit_solde_restant = 0

    vente.statut = "annulee"
    vente.commentaire = (
        f"[ANNULÉE] {motif.strip()} — par {current_user.full_name}"
        + (f"\n{vente.commentaire}" if vente.commentaire else "")
    )
    vente.annule_motif = motif.strip()
    vente.annule_par_nom = current_user.full_name
    vente.annule_le = utcnow()
    db.session.commit()
    return vente


def corriger_vente(vente, data, motif, current_user):
    """Corrige une vente déjà validée sans passer par une annulation : lignes
    (quantité, ajout, suppression), moyen(s) de paiement, montant payé et
    client — le point le plus fréquent restant l'erreur de moyen de paiement
    (retour utilisateur : "encaissé en espèces alors que le client a payé par
    banque"), sans devoir refaire tout le ticket.

    Reprend l'ancien impact stock/comptes financiers/crédit ligne par ligne,
    puis applique le nouveau — même principe qu'annuler_vente() +
    enregistrer_vente() combinés, mais en conservant le même Vente.id (donc
    la même place dans l'historique client et les rapports) plutôt que
    d'annuler et recréer un ticket. Un motif est obligatoire, comme pour
    toute correction sensible (§ droit "corrections")."""
    if vente.statut != "validee":
        raise VenteError("Cette vente est annulée — elle ne peut pas être corrigée.")
    if not motif or not motif.strip():
        raise VenteError("Un motif est obligatoire pour corriger une vente.")

    # Une vente à crédit déjà partiellement remboursée ne peut pas être
    # recalculée automatiquement (même garde-fou qu'annuler_vente : un
    # reversal FIFO partiel désynchroniserait le crédit d'autres ventes du
    # même client).
    if vente.montant_credit > 0 and vente.credit_solde_restant < vente.montant_credit:
        raise VenteError(
            "Cette vente à crédit a déjà commencé à être remboursée — "
            "seul le classement (poste, catégorie, projet) peut encore être corrigé."
        )

    ancien_client = vente.client

    # --- Client -----------------------------------------------------------
    client = None
    client_id = data.get("client_id")
    if client_id:
        client = db.session.get(Client, client_id)
        if client is None or client.is_archived:
            raise VenteError("Client invalide.")
        vente.client_id = client.id
        vente.client_nom = client.nom
    else:
        vente.client_id = None
        vente.client_nom = (data.get("client_nom") or "").strip() or None

    vente.commentaire = (data.get("commentaire") or "").strip() or None

    # --- Lignes : quantité modifiée, ligne supprimée, ligne ajoutée --------
    # Chaque écart de quantité (existant vs nouveau) reçoit son propre
    # mouvement de stock inverse/complémentaire — jamais un simple recalcul
    # du stock affiché, pour garder la même traçabilité (MouvementStock)
    # qu'une vente ou une annulation normale.
    sous_total = 0
    for ligne in list(vente.lignes):
        ligne_data = (data.get("lignes") or {}).get(ligne.id)
        if ligne_data is None:
            sous_total += ligne.total_ligne
            continue

        nouvelle_quantite = int(ligne_data.get("quantite", ligne.quantite) or 0)
        if nouvelle_quantite < 1:
            # Suppression de la ligne : tout le stock qu'elle avait décrémenté est restitué.
            produit = ligne.produit
            if produit is not None and not produit.stock_illimite:
                enregistrer_mouvement(
                    produit, "entree", "correction", ligne.quantite, current_user,
                    commentaire=f"Correction vente #{vente.id} — ligne supprimée",
                    reference_type="vente", reference_id=vente.id,
                )
            vente.lignes.remove(ligne)
            continue

        if nouvelle_quantite != ligne.quantite:
            produit = ligne.produit
            ecart = nouvelle_quantite - ligne.quantite
            if produit is not None and not produit.stock_illimite:
                enregistrer_mouvement(
                    produit, "sortie" if ecart > 0 else "entree", "correction", abs(ecart), current_user,
                    commentaire=f"Correction vente #{vente.id} — quantité {ligne.quantite} → {nouvelle_quantite}",
                    reference_type="vente", reference_id=vente.id,
                )
            ligne.quantite = nouvelle_quantite

        ligne.calculer_total()
        sous_total += ligne.total_ligne

    nouvelle_ligne_data = data.get("nouvelle_ligne")
    if nouvelle_ligne_data and nouvelle_ligne_data.get("produit_id"):
        produit = db.session.get(Produit, nouvelle_ligne_data.get("produit_id"))
        if produit is None or produit.is_archived:
            raise VenteError("Produit invalide pour la ligne ajoutée.")
        quantite = int(nouvelle_ligne_data.get("quantite") or 0)
        if quantite < 1:
            raise VenteError("Quantité invalide pour la ligne ajoutée.")

        if produit.prix_libre:
            prix_unitaire = int(nouvelle_ligne_data.get("prix_unitaire") or 0)
            if prix_unitaire <= 0:
                raise VenteError(f"Montant invalide pour {produit.name}.")
        else:
            prix_unitaire = produit.prix_pour(vente.type_tarif.code)
            if prix_unitaire is None:
                raise VenteError(f"Aucun tarif {vente.type_tarif.label} pour {produit.name}.")

        ligne = LigneVente(
            produit_id=produit.id, produit_nom=produit.name, poste_id=produit.poste_id,
            projet_id=produit.projet_id, categorie_id=produit.categorie_id,
            sous_categorie_id=produit.sous_categorie_id, quantite=quantite, prix_unitaire=prix_unitaire,
        )
        ligne.calculer_total()
        sous_total += ligne.total_ligne
        if not produit.stock_illimite:
            enregistrer_mouvement(
                produit, "sortie", "vente", quantite, current_user,
                commentaire=f"Correction vente #{vente.id} — ligne ajoutée",
                reference_type="vente", reference_id=vente.id,
            )
        vente.lignes.append(ligne)

    if not vente.lignes:
        raise VenteError("Une vente ne peut pas rester vide — annulez-la plutôt que de supprimer toutes ses lignes.")

    total = max(0, sous_total - vente.remise)
    vente.sous_total = sous_total
    vente.total = total

    # --- Crédit client : reprise de l'ancien impact avant nouveau calcul ---
    if vente.montant_credit > 0 and ancien_client is not None:
        ancien_client.solde_credit -= vente.credit_solde_restant
    vente.montant_credit = 0
    vente.credit_solde_restant = 0

    # --- Paiements : repris intégralement puis réappliqués -----------------
    # Le point le plus fréquent (retour utilisateur) : corriger uniquement le
    # moyen de paiement d'une vente déjà encaissée (ex. "espèces" saisi par
    # erreur au lieu de "banque"), sans toucher au reste du ticket.
    for paiement in list(vente.paiements):
        debiter_compte(paiement.moyen_paiement.compte_financier, paiement.montant)
        vente.paiements.remove(paiement)

    paiements_data = data.get("paiements") or []
    a_credit = bool(data.get("a_credit"))
    if a_credit and client is None:
        raise VenteError("La vente à crédit nécessite un client enregistré.")

    total_paye = 0
    paiement_devise_etrangere = False
    for paiement_data in paiements_data:
        montant = int(paiement_data.get("montant") or 0)
        if montant <= 0:
            continue
        moyen = db.session.get(MoyenPaiement, paiement_data.get("moyen_paiement_id"))
        if moyen is None or moyen.is_archived:
            raise VenteError("Moyen de paiement invalide.")
        vente.paiements.append(VentePaiement(moyen_paiement_id=moyen.id, montant=montant))
        crediter_compte(moyen.compte_financier, montant)
        if moyen.compte_financier.devise == "Ar":
            total_paye += montant
        else:
            paiement_devise_etrangere = True

    montant_restant = 0 if paiement_devise_etrangere else total - total_paye
    if montant_restant > 0:
        if not a_credit:
            raise VenteError(f"Le total payé ({total_paye}) ne correspond pas au total du ticket ({total}).")
        vente.montant_credit = montant_restant
        vente.credit_solde_restant = montant_restant
        client.solde_credit += montant_restant
    elif montant_restant < 0:
        raise VenteError(f"Le total payé ({total_paye}) dépasse le total du ticket ({total}).")

    vente.derniere_correction_motif = motif.strip()
    vente.derniere_correction_par_nom = current_user.full_name
    vente.derniere_correction_le = utcnow()

    db.session.commit()
    return vente
