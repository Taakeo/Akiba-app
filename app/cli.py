from datetime import datetime, timedelta, timezone

import click

from .extensions import db
from .models import (
    DEFAULT_PROFILES,
    Categorie,
    CompteFinancier,
    Fournisseur,
    MoyenPaiement,
    Poste,
    PrixProduit,
    Produit,
    Profile,
    SousCategorie,
    SubProfile,
    TypeTarif,
    enregistrer_mouvement,
)


def register_cli(app):
    @app.cli.command("seed-db")
    def seed_db():
        """Crée les profils par défaut, un compte administrateur, et des données
        de démonstration (postes, catégories, produits, comptes financiers)."""
        admin = _seed_profils_et_admin()
        _seed_catalogue_demo(admin)
        click.echo("Base initialisée : profils, comptes financiers et catalogue de démonstration.")

    @app.cli.command("purge-suspended-users")
    def purge_suspended_users():
        """Supprime les sous-profils suspendus depuis plus de
        SUBPROFILE_SUSPENSION_PURGE_DAYS jours (§3.2 spec). Les opérations déjà
        enregistrées par ces utilisateurs sont conservées (FK nullable + nom
        figé en texte sur chaque opération) — seul l'enregistrement utilisateur
        disparaît. À planifier via un ordonnanceur du système d'exploitation
        (ex. Planificateur de tâches Windows) une fois le déploiement final
        choisi ; cette commande ne s'auto-exécute pas en arrière-plan."""
        noms = _purger_utilisateurs_suspendus(app)
        if noms:
            click.echo(f"{len(noms)} sous-profil(s) supprimé(s) : {', '.join(noms)}")
        else:
            click.echo("Aucun sous-profil à purger.")


class _UtilisateurSysteme:
    full_name = "Système (purge automatique)"


def _purger_utilisateurs_suspendus(app):
    seuil = datetime.now(timezone.utc) - timedelta(days=app.config["SUBPROFILE_SUSPENSION_PURGE_DAYS"])
    a_purger = SubProfile.query.filter(
        SubProfile.is_active.is_(False),
        SubProfile.suspended_at.isnot(None),
        SubProfile.suspended_at <= seuil,
    ).all()

    noms = [sp.full_name for sp in a_purger]
    for sous_profil in a_purger:
        db.session.delete(sous_profil)
    db.session.commit()

    if noms:
        from .admin.backup_service import log_audit

        log_audit(app, "utilisateurs_purges", ", ".join(noms), _UtilisateurSysteme())

    return noms


def _seed_profils_et_admin():
    for data in DEFAULT_PROFILES:
        if Profile.query.filter_by(code=data["code"]).first():
            continue
        profile = Profile(code=data["code"], name=data["name"], icon=data["icon"])
        profile.permissions = data["permissions"]
        db.session.add(profile)
    db.session.commit()

    admin_profile = Profile.query.filter_by(code="administrateur").first()
    admin = SubProfile.query.filter_by(profile_id=admin_profile.id).first()
    if admin is None:
        admin = SubProfile(profile_id=admin_profile.id, full_name="Administrateur")
        admin.set_pin("0000")
        db.session.add(admin)
        db.session.commit()
        click.echo("Compte administrateur créé : PIN 0000 (à changer immédiatement).")
    return admin


def _get_or_create(model, defaults=None, **lookup):
    instance = model.query.filter_by(**lookup).first()
    if instance:
        return instance
    instance = model(**lookup, **(defaults or {}))
    db.session.add(instance)
    db.session.flush()
    return instance


def _seed_catalogue_demo(admin):
    if Produit.query.first():
        return  # catalogue déjà initialisé, on ne duplique pas

    # Comptes financiers et moyens de paiement (§7.4 spec) — une seule caisse
    # physique à la fois (celle sur laquelle s'ouvrent/se ferment les
    # sessions de caisse, §2 spec mono-poste) : Caisse Euro n'est qu'une
    # petite caisse d'appoint en devise étrangère, pas le tiroir suivi par
    # les sessions (retour utilisateur du 09/08/2026 — les deux comptes
    # avaient auparavant is_caisse_physique=True simultanément, ambigu).
    caisse_ariary = _get_or_create(
        CompteFinancier, name="Caisse Ariary", defaults={"devise": "Ar", "is_caisse_physique": True}
    )
    caisse_euro = _get_or_create(CompteFinancier, name="Caisse Euro", defaults={"devise": "€"})
    orange_money = _get_or_create(CompteFinancier, name="Orange Money n°1", defaults={"devise": "Ar"})
    mvola = _get_or_create(CompteFinancier, name="Compte Mvola", defaults={"devise": "Ar"})
    airtel = _get_or_create(CompteFinancier, name="Compte Airtel", defaults={"devise": "Ar"})
    bmoi = _get_or_create(CompteFinancier, name="BMOI", defaults={"devise": "Ar"})
    # Compte cible du prélèvement fait à chaque clôture de caisse — l'argent
    # du PDV ne le met à jour qu'à ce moment-là, jamais avant (§ amélioration,
    # retour utilisateur du 08/08/2026).
    compte_akiba = _get_or_create(CompteFinancier, name="Compte Akiba", defaults={"devise": "Ar", "is_compte_akiba": True})

    _get_or_create(
        MoyenPaiement,
        name="Espèces Ariary",
        compte_financier_id=caisse_ariary.id,
        defaults={"ouvre_tiroir": True, "is_default": True},
    )
    _get_or_create(
        MoyenPaiement,
        name="Espèces Euro",
        compte_financier_id=caisse_euro.id,
        defaults={"ouvre_tiroir": True},
    )
    _get_or_create(MoyenPaiement, name="Orange Money", compte_financier_id=orange_money.id)
    _get_or_create(MoyenPaiement, name="Mvola", compte_financier_id=mvola.id)
    _get_or_create(MoyenPaiement, name="Airtel Money", compte_financier_id=airtel.id)
    _get_or_create(MoyenPaiement, name="Banque BMOI", compte_financier_id=bmoi.id)
    # Même nom que le moyen du tiroir PDV mais compte différent : jamais
    # proposé à l'encaissement du PDV (visible_pdv=False), utilisable pour
    # les achats/mouvements payés directement depuis le Compte Akiba.
    _get_or_create(
        MoyenPaiement,
        name="Espèces Ariary",
        compte_financier_id=compte_akiba.id,
        defaults={"visible_pdv": False},
    )

    # Fournisseurs (§5.3 spec)
    fournisseur_cacao = _get_or_create(
        Fournisseur, name="Coopérative Cacao Sud", defaults={"telephone": "032 00 000 00"}
    )

    # Types de tarif (§6.4 spec)
    tarif_standard = _get_or_create(
        TypeTarif, code="standard", defaults={"label": "Standard", "ordre": 1, "is_default": True}
    )
    tarif_adherent = _get_or_create(TypeTarif, code="adherent", defaults={"label": "Adhérent", "ordre": 2})
    tarif_resident = _get_or_create(TypeTarif, code="resident", defaults={"label": "Résident", "ordre": 3})
    tarif_touriste = _get_or_create(TypeTarif, code="touriste", defaults={"label": "Touriste", "ordre": 4})
    tarif_grossiste = _get_or_create(TypeTarif, code="grossiste", defaults={"label": "Grossiste", "ordre": 5})

    # Postes (§4.3 spec) — reprend les 5 pôles réels d'Akiba (fichier
    # "liste poste et catégories.xlsx" fourni par l'association), et non plus
    # une liste de démonstration : Boutique_Atelier, Hebergement_Restauration
    # et Dispensaire sont vendables au PDV (§6.3), Général et École servent
    # surtout à classer achats/dépenses.
    postes = {
        name: _get_or_create(Poste, name=name, defaults={"icon": icon})
        for name, icon in [
            ("GENERAL", "account_balance"),
            ("ECOLE", "school"),
            ("BOUTIQUE_ATELIER", "storefront"),
            ("HEBERGEMENT_RESTAURATION", "restaurant"),
            ("DISPENSAIRE", "medical_services"),
        ]
    }

    # Catégories (et sous-catégories) réelles par poste, reprises telles
    # quelles du classeur fourni par Akiba — chaque catégorie n'appartient
    # qu'à un seul poste (voir Categorie.__table_args__).
    structure = {
        "GENERAL": {
            "Achats_general": ["Contruction", "Agriculture", "Divers"],
            "Ventes": [],
            "Salaires_general": ["Fixes", "Journaliers"],
            "Dons_general": ["Assadem", "Dons directs"],
            "Financements": ["Valrhona", "Achats_valrhona", "Tsiky Zanaka"],
            "Administratif": ["Bureautique", "Frais administratifs"],
        },
        "ECOLE": {
            "Assadem": ["Parrainage", "Dons"],
            "Don_ecole": ["Assadem", "Dons directs"],
            "Ecolage": ["Inscription"],
            "Salaires_Ecole": ["Enseignants", "Cantine"],
            "Fournitures": ["Blouses"],
            "Materiel_pedagogique": [],
            "Batiment_ecole": [],
            "Cantine": ["Parents", "Akiba", "depenses_cantine"],
            "Ecolage_boursier": ["Personnel_akiba", "Exterieur"],
            "Divers_ecole": ["Fripe don"],
        },
        "BOUTIQUE_ATELIER": {
            "Vanille": ["Achats vanille", "Vente vanille", "Autres"],
            "Chocolat": ["Achats cacao", "Vente chocolat"],
            "Cafe": ["Achat café", "Vente café"],
            "Epices": ["Achat épices", "Ventes épices"],
            "Couture": ["Achats couture", "Ventes couture"],
            "Alcools": ["Achats Alcool", "Ventes alcool"],
            "Bijoux": ["Achat Bijoux", "Ventes bijoux"],
            "Jus": ["Achats fruits", "Ventes jus"],
            "THB": ["Achat THB", "Vente THB"],
            "Ventes_autres": ["Livres", "Couches"],
            "Vinaigre": ["Achat Vinaigre", "Ventes vinaigre"],
            "Tee-shirts": ["Achat tee shirt", "Vente tee shirt"],
            "Infusions": ["Achat infusion", "Vente infusion"],
            "Pourboires": [],
            "Huiles Essentielles": ["Achat HE", "Ventes HE"],
            "Salaires_boutique": [],
            "Primes": [],
            "Achats_boutique": ["Packeging", "Fruits", "Matériel"],
        },
        "HEBERGEMENT_RESTAURATION": {
            "Entrée_tourisme": [],
            "Entrée_Volontaire": [],
            "Achats_cuisine": [],
            "Entrée_Formation": [],
            "Dépenses_Formation": [],
            "Divers_Tourisme": [],
            "Achats_divers": [],
            "Salaires_cuisine": [],
            "Guidage": ["Entrées_guidage", "Primes_guidage", "Salaire_guidage"],
        },
        "DISPENSAIRE": {
            "Batiments_dispensaire": ["Bois", "Charpentiers"],
            "Achats_matériel": ["Medicaments"],
            "Entrées": ["Rose des sables"],
            "Salaires_dispensaire": [],
        },
    }

    categories = {}  # (poste_name, categorie_name) -> Categorie
    sous_categories = {}  # (poste_name, categorie_name, sous_categorie_name) -> SousCategorie
    for poste_name, categories_du_poste in structure.items():
        poste = postes[poste_name]
        for ordre, (categorie_nom, sous_noms) in enumerate(categories_du_poste.items()):
            categorie = _get_or_create(
                Categorie, poste_id=poste.id, name=categorie_nom, defaults={"ordre": ordre}
            )
            categories[(poste_name, categorie_nom)] = categorie
            for sous_nom in sous_noms:
                sous_categories[(poste_name, categorie_nom, sous_nom)] = _get_or_create(
                    SousCategorie, categorie_id=categorie.id, name=sous_nom
                )

    demo_produits = [
        {
            "name": "Tablette Chocolat 70%",
            "categorie": categories[("BOUTIQUE_ATELIER", "Chocolat")],
            "sous_categorie": sous_categories[("BOUTIQUE_ATELIER", "Chocolat", "Vente chocolat")],
            "poste": postes["BOUTIQUE_ATELIER"],
            "fournisseur": fournisseur_cacao,
            "stock": 40,
            "seuil": 10,
            "prix": {"standard": 8000, "adherent": 7000, "resident": 7500, "touriste": 8000, "grossiste": 6000},
        },
        {
            "name": "Café moulu 250g",
            "categorie": categories[("BOUTIQUE_ATELIER", "Cafe")],
            "sous_categorie": sous_categories[("BOUTIQUE_ATELIER", "Cafe", "Vente café")],
            "poste": postes["BOUTIQUE_ATELIER"],
            "fournisseur": fournisseur_cacao,
            "stock": 25,
            "seuil": 5,
            "prix": {"standard": 12000, "adherent": 10500, "resident": 11000, "touriste": 12000, "grossiste": 9000},
        },
        {
            "name": "Huile essentielle Lavande 30ml",
            "categorie": categories[("BOUTIQUE_ATELIER", "Huiles Essentielles")],
            "sous_categorie": sous_categories[("BOUTIQUE_ATELIER", "Huiles Essentielles", "Ventes HE")],
            "poste": postes["BOUTIQUE_ATELIER"],
            "fournisseur": None,
            "stock": 3,
            "seuil": 5,
            "prix": {"standard": 22000, "adherent": 20000, "resident": 21000, "touriste": 22000, "grossiste": 17000},
        },
        {
            "name": "Visite guidée du site Akiba",
            "categorie": categories[("HEBERGEMENT_RESTAURATION", "Guidage")],
            "sous_categorie": sous_categories[("HEBERGEMENT_RESTAURATION", "Guidage", "Entrées_guidage")],
            "poste": postes["HEBERGEMENT_RESTAURATION"],
            "fournisseur": None,
            "stock": 999,
            "seuil": None,
            "prix": {"standard": 25000, "adherent": 15000, "resident": 10000, "touriste": 25000, "grossiste": 20000},
        },
        {
            # Prix libre (§6.4 spec) : pas de tarifs fixes, le montant est saisi
            # à la vente — voir Produit.prix_libre et pos/services.py.
            "name": "Pourboire",
            "categorie": categories[("BOUTIQUE_ATELIER", "Pourboires")],
            "sous_categorie": None,
            "poste": postes["BOUTIQUE_ATELIER"],
            "fournisseur": None,
            "stock": 0,
            "seuil": None,
            "stock_illimite": True,
            "prix_libre": True,
            "prix": {},
        },
    ]

    tarifs_par_code = {
        "standard": tarif_standard,
        "adherent": tarif_adherent,
        "resident": tarif_resident,
        "touriste": tarif_touriste,
        "grossiste": tarif_grossiste,
    }

    for data in demo_produits:
        produit = Produit(
            name=data["name"],
            categorie_id=data["categorie"].id,
            sous_categorie_id=data["sous_categorie"].id if data["sous_categorie"] else None,
            poste_id=data["poste"].id,
            fournisseur_principal_id=data["fournisseur"].id if data["fournisseur"] else None,
            stock_quantite=0,
            seuil_alerte=data["seuil"],
            stock_illimite=data.get("stock_illimite", False),
            prix_libre=data.get("prix_libre", False),
        )
        db.session.add(produit)
        db.session.flush()

        if data["stock"]:
            enregistrer_mouvement(
                produit, "entree", "correction", data["stock"], admin, commentaire="Stock initial (seed)"
            )

        for code, montant in data["prix"].items():
            db.session.add(
                PrixProduit(produit_id=produit.id, type_tarif_id=tarifs_par_code[code].id, montant=montant)
            )

    db.session.commit()
