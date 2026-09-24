from ..extensions import db
from ..models import Facture, FactureCompteur, ParametresLegaux


class FactureError(ValueError):
    pass


def generer_facture(client, ventes, current_user):
    """Émet une facture officielle numérotée à partir d'un ou plusieurs
    tickets déjà encaissés d'un même client. Toutes les vérifications qui
    suivent bloquent volontairement plutôt que de "faire au mieux" — une
    facture officielle mal formée (client sans adresse, ticket déjà facturé
    ailleurs...) est plus coûteuse à corriger après coup qu'à refuser
    d'emblée."""

    if not client.nom or not client.nom.strip():
        raise FactureError("Le client doit avoir un nom renseigné pour être facturé.")
    if not client.adresse or not client.adresse.strip():
        raise FactureError(
            "L'adresse du client est obligatoire sur une facture officielle. "
            "Complétez la fiche client avant de facturer."
        )

    if not ventes:
        raise FactureError("Sélectionnez au moins un ticket à facturer.")

    for vente in ventes:
        if vente.client_id != client.id:
            raise FactureError(f"Le ticket #{vente.id} n'appartient pas à ce client.")
        if vente.statut != "validee":
            raise FactureError(f"Le ticket #{vente.id} n'est pas une vente valide.")
        if vente.facture_id is not None:
            raise FactureError(f"Le ticket #{vente.id} est déjà inclus dans une autre facture.")

    legal = ParametresLegaux.get()

    facture = Facture(
        numero=FactureCompteur.numero_suivant(),
        client_id=client.id,
        client_nom=client.nom,
        client_adresse=client.adresse,
        emetteur_raison_sociale=legal.raison_sociale,
        emetteur_adresse=legal.adresse,
        emetteur_telephone=legal.telephone,
        emetteur_email=legal.email,
        emetteur_nif=legal.nif,
        emetteur_stat=legal.stat,
        emetteur_rcs=legal.rcs,
        sous_total=sum(v.sous_total for v in ventes),
        remise=sum(v.remise for v in ventes),
        total=sum(v.total for v in ventes),
        created_by_subprofile_id=current_user.id,
        created_by_name=current_user.full_name,
    )
    db.session.add(facture)
    db.session.flush()

    for vente in ventes:
        vente.facture_id = facture.id

    db.session.commit()
    return facture


def generer_facture_externe(client, ventes_externes, current_user):
    """Émet une facture officielle numérotée à partir d'une ou plusieurs
    ventes externes déjà enregistrées d'un même client (§ amélioration
    facture ventes externes) — même mécanisme et mêmes exigences que
    generer_facture() pour les ventes PDV (client nommé + adressé,
    numérotation FA-xxxxxx partagée), mais jamais mélangée avec des tickets
    PDV sur une même facture : les deux circuits restent distincts."""

    if not client.nom or not client.nom.strip():
        raise FactureError("Le client doit avoir un nom renseigné pour être facturé.")
    if not client.adresse or not client.adresse.strip():
        raise FactureError(
            "L'adresse du client est obligatoire sur une facture officielle. "
            "Complétez la fiche client avant de facturer."
        )

    if not ventes_externes:
        raise FactureError("Sélectionnez au moins une vente externe à facturer.")

    for vente_externe in ventes_externes:
        if vente_externe.client_id != client.id:
            raise FactureError(f"La vente externe #{vente_externe.id} n'appartient pas à ce client.")
        if vente_externe.is_annule:
            raise FactureError(f"La vente externe #{vente_externe.id} est annulée.")
        if vente_externe.facture_id is not None:
            raise FactureError(f"La vente externe #{vente_externe.id} est déjà incluse dans une autre facture.")

    legal = ParametresLegaux.get()
    total = sum(v.montant_total for v in ventes_externes)

    facture = Facture(
        numero=FactureCompteur.numero_suivant(),
        client_id=client.id,
        client_nom=client.nom,
        client_adresse=client.adresse,
        emetteur_raison_sociale=legal.raison_sociale,
        emetteur_adresse=legal.adresse,
        emetteur_telephone=legal.telephone,
        emetteur_email=legal.email,
        emetteur_nif=legal.nif,
        emetteur_stat=legal.stat,
        emetteur_rcs=legal.rcs,
        sous_total=total,
        remise=0,
        total=total,
        created_by_subprofile_id=current_user.id,
        created_by_name=current_user.full_name,
    )
    db.session.add(facture)
    db.session.flush()

    for vente_externe in ventes_externes:
        vente_externe.facture_id = facture.id

    db.session.commit()
    return facture
