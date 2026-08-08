def _login_as(client, profile_id, subprofile_id, pin):
    client.post(f"/auth/profil/{profile_id}/utilisateur/{subprofile_id}", data={"pin": pin})


def _vente_de_seller(client, catalogue, seller_profile, seller_subprofile):
    """La vente doit être faite par le vendeur, mais les tests inspectent le
    journal en tant qu'admin ensuite — le login est donc explicitement repris
    en main plutôt que de superposer login_admin et login_seller (les deux
    partagent le même client, seul le dernier login reste actif)."""
    _login_as(client, seller_profile, seller_subprofile, "1234")
    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    client.post(
        "/pos/vente",
        json={
            "type_tarif_id": catalogue["type_tarif_id"],
            "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 1, "remise": 0, "offert": False}],
            "paiements": [{"moyen_paiement_id": catalogue["moyen_paiement_id"], "montant": 8000}],
        },
    )


def test_journal_requires_permission(client, login_seller):
    assert client.get("/admin/journal").status_code == 403


def test_journal_agrege_une_vente_et_un_achat(
    client, catalogue, seller_profile, seller_subprofile, admin_profile, admin_subprofile
):
    # Vente enregistrée par le vendeur, consultée ensuite par l'admin — le
    # journal doit remonter le bon nom d'utilisateur, quel que soit qui a
    # fait l'opération (retour utilisateur du 08/08/2026 : "toutes les
    # manipulations faites par les différents profils incluant l'admin").
    _vente_de_seller(client, catalogue, seller_profile, seller_subprofile)
    _login_as(client, admin_profile, admin_subprofile, "9999")

    response = client.get("/admin/journal")
    assert response.status_code == 200
    assert b"Sarah" in response.data
    assert "8 000".encode() in response.data or b"8000" in response.data


def test_journal_filtre_par_module(
    client, catalogue, seller_profile, seller_subprofile, admin_profile, admin_subprofile
):
    _vente_de_seller(client, catalogue, seller_profile, seller_subprofile)
    _login_as(client, admin_profile, admin_subprofile, "9999")

    reponse_ventes = client.get("/admin/journal?module=ventes")
    assert b"Vente #1" in reponse_ventes.data

    reponse_achats = client.get("/admin/journal?module=achats")
    assert b"Vente #1" not in reponse_achats.data


def test_journal_filtre_par_utilisateur(
    client, catalogue, seller_profile, seller_subprofile, admin_profile, admin_subprofile
):
    _vente_de_seller(client, catalogue, seller_profile, seller_subprofile)
    _login_as(client, admin_profile, admin_subprofile, "9999")

    reponse = client.get("/admin/journal?utilisateur=Sarah")
    assert b"Vente #1" in reponse.data

    reponse_vide = client.get("/admin/journal?utilisateur=Personne-Inexistante")
    assert b"Vente #1" not in reponse_vide.data
    assert "Aucune activité".encode() in reponse_vide.data


def test_creation_profil_est_journalisee(client, login_admin):
    client.post(
        "/admin/profils/nouveau",
        data={"name": "Bénévole test", "icon": "badge", "permissions": ["point_de_vente"]},
    )
    response = client.get("/admin/journal?module=administration")
    assert response.status_code == 200
    assert b"profil_cree" in response.data
    assert "Bénévole test".encode() in response.data


def test_creation_utilisateur_est_journalisee(client, login_admin):
    from app.models import Profile

    profile = Profile.query.first()
    client.post("/admin/utilisateurs/nouveau", data={"profile_id": str(profile.id), "full_name": "Nouvel Employé"})

    response = client.get("/admin/journal?module=administration")
    assert b"utilisateur_cree" in response.data
    assert "Nouvel Employé".encode() in response.data
