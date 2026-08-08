def test_menu_vendeur_ne_montre_que_ses_droits(client, login_seller):
    """Le Vendeur (permissions: point_de_vente, caisse) ne doit voir dans le
    menu que ce à quoi il a droit — pas juste être bloqué s'il devine l'URL."""
    response = client.get("/")
    page = response.data.decode("utf-8")

    assert "Point de Vente" in page
    assert "Comptes" in page

    for label_interdit in [
        "Achats",
        "Stocks",
        "Production",
        "Ressources humaines",
        "Clients",
        "Rapports",
        "Administration",
    ]:
        assert label_interdit not in page, f"'{label_interdit}' ne devrait pas apparaître pour un Vendeur"


def test_menu_admin_montre_tout(client, login_admin):
    """L'Administrateur (permissions: *) doit voir l'intégralité du menu."""
    response = client.get("/")
    page = response.data.decode("utf-8")

    for label in [
        "Point de Vente",
        "Achats",
        "Stocks",
        "Production",
        "Ressources humaines",
        "Clients",
        "Comptes",
        "Rapports",
        "Administration",
    ]:
        assert label in page, f"'{label}' devrait apparaître pour l'Administrateur"


def test_menu_comptable_ne_voit_que_rapports(client, app, db):
    from app.models import Profile, SubProfile

    with app.app_context():
        profile = Profile(code="comptable", name="Comptable", icon="account_balance")
        profile.permissions = ["rapports"]
        db.session.add(profile)
        db.session.commit()

        sub_profile = SubProfile(profile_id=profile.id, full_name="Comptable Test")
        sub_profile.set_pin("5555")
        db.session.add(sub_profile)
        db.session.commit()
        profile_id, sub_profile_id = profile.id, sub_profile.id

    client.post(f"/auth/profil/{profile_id}/utilisateur/{sub_profile_id}", data={"pin": "5555"})

    response = client.get("/")
    page = response.data.decode("utf-8")

    assert "Rapports" in page
    # Le tableau de bord affiche un résumé des comptes même au Comptable (lecture
    # seule, justifiée par le droit "rapports") — mais pas les autres sections.
    assert "Comptes" in page
    for label_interdit in ["Point de Vente", "Achats", "Stocks", "Administration"]:
        assert label_interdit not in page

    # Côté route, la gestion opérationnelle de caisse reste bloquée : le
    # Comptable voit le solde sur le tableau de bord, mais ne peut pas
    # ouvrir/fermer la caisse ni saisir un mouvement (droit "caisse" requis).
    assert client.get("/pos/").status_code == 403
    assert client.get("/achats/").status_code == 403
    assert client.get("/caisse/").status_code == 403
    assert client.get("/rapports/").status_code == 200
