def test_premier_demarrage_cree_les_profils_et_un_admin_avec_pin_aleatoire(app, db):
    from app.bootstrap import premier_demarrage_si_necessaire
    from app.models import Profile, SubProfile

    with app.app_context():
        pin = premier_demarrage_si_necessaire()

        assert pin is not None
        assert len(pin) == 4
        assert pin.isdigit()
        assert pin != "0000"  # jamais le PIN de dev fixe

        assert Profile.query.count() == 4
        admin_profile = Profile.query.filter_by(code="administrateur").first()
        assert admin_profile is not None
        assert admin_profile.has_permission("*")

        admin = SubProfile.query.filter_by(profile_id=admin_profile.id).first()
        assert admin is not None
        assert admin.check_pin(pin)


def test_premier_demarrage_ne_fait_rien_si_deja_initialise(app, db):
    from app.bootstrap import premier_demarrage_si_necessaire
    from app.models import Profile

    with app.app_context():
        premier_demarrage_si_necessaire()
        nb_profils_apres_premier_appel = Profile.query.count()

        resultat = premier_demarrage_si_necessaire()

        assert resultat is None
        assert Profile.query.count() == nb_profils_apres_premier_appel


def test_premier_demarrage_naucun_catalogue_de_demo(app, db):
    """Contrairement à `flask seed-db` (dev), le bootstrap de production ne
    doit créer aucune donnée métier fictive — une vraie association ne doit
    pas avoir à supprimer des produits factices à la main."""
    from app.bootstrap import premier_demarrage_si_necessaire
    from app.models import Poste, Produit

    with app.app_context():
        premier_demarrage_si_necessaire()
        assert Produit.query.count() == 0
        assert Poste.query.count() == 0
