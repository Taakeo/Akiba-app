from datetime import datetime, timedelta, timezone


def test_purge_supprime_les_suspendus_au_dela_du_delai(app, db, tmp_path):
    from app.cli import _purger_utilisateurs_suspendus
    from app.models import Profile, SubProfile

    app.config["AUDIT_LOG_PATH"] = tmp_path / "audit.log"
    app.config["SUBPROFILE_SUSPENSION_PURGE_DAYS"] = 90

    with app.app_context():
        profile = Profile(code="vendeur", name="Vendeur")
        profile.permissions = ["point_de_vente"]
        db.session.add(profile)
        db.session.commit()

        ancien = SubProfile(profile_id=profile.id, full_name="Ancien Suspendu")
        ancien.set_pin("1111")
        ancien.is_active = False
        ancien.suspended_at = datetime.now(timezone.utc) - timedelta(days=120)
        db.session.add(ancien)

        recent = SubProfile(profile_id=profile.id, full_name="Récemment Suspendu")
        recent.set_pin("2222")
        recent.is_active = False
        recent.suspended_at = datetime.now(timezone.utc) - timedelta(days=10)
        db.session.add(recent)

        actif = SubProfile(profile_id=profile.id, full_name="Toujours Actif")
        actif.set_pin("3333")
        db.session.add(actif)
        db.session.commit()

        noms = _purger_utilisateurs_suspendus(app)

        assert noms == ["Ancien Suspendu"]
        restants = {sp.full_name for sp in SubProfile.query.all()}
        assert restants == {"Récemment Suspendu", "Toujours Actif"}


def test_purge_conserve_l_historique_des_operations(app, db, tmp_path):
    from app.cli import _purger_utilisateurs_suspendus
    from app.models import CaisseSession, CompteFinancier, Profile, SubProfile, Vente

    app.config["AUDIT_LOG_PATH"] = tmp_path / "audit.log"

    with app.app_context():
        profile = Profile(code="vendeur", name="Vendeur")
        profile.permissions = ["point_de_vente"]
        db.session.add(profile)
        db.session.commit()

        vendeur = SubProfile(profile_id=profile.id, full_name="Sarah")
        vendeur.set_pin("1234")
        vendeur.is_active = False
        vendeur.suspended_at = datetime.now(timezone.utc) - timedelta(days=200)
        db.session.add(vendeur)
        db.session.commit()

        caisse = CompteFinancier(name="Caisse Ariary", devise="Ar", is_caisse_physique=True)
        db.session.add(caisse)
        db.session.flush()
        session = CaisseSession(
            compte_financier_id=caisse.id, fond_ouverture=0, ouverte_par_nom="Sarah"
        )
        db.session.add(session)
        db.session.flush()

        vente = Vente(
            caisse_session_id=session.id,
            type_tarif_id=1,
            created_by_subprofile_id=vendeur.id,
            created_by_name="Sarah",
            total=5000,
        )
        db.session.add(vente)
        db.session.commit()
        vente_id = vente.id

        _purger_utilisateurs_suspendus(app)

        vente_apres = db.session.get(Vente, vente_id)
        assert vente_apres is not None
        assert vente_apres.created_by_name == "Sarah"  # le nom reste lisible
        assert SubProfile.query.filter_by(full_name="Sarah").first() is None


def test_purge_journalise_dans_l_audit(app, db, tmp_path):
    from app.admin.backup_service import lire_audit_log
    from app.cli import _purger_utilisateurs_suspendus
    from app.models import Profile, SubProfile

    audit_path = tmp_path / "audit.log"
    app.config["AUDIT_LOG_PATH"] = audit_path

    with app.app_context():
        profile = Profile(code="vendeur", name="Vendeur")
        profile.permissions = ["point_de_vente"]
        db.session.add(profile)
        db.session.commit()

        ancien = SubProfile(profile_id=profile.id, full_name="Ancien Suspendu")
        ancien.set_pin("1111")
        ancien.is_active = False
        ancien.suspended_at = datetime.now(timezone.utc) - timedelta(days=120)
        db.session.add(ancien)
        db.session.commit()

        _purger_utilisateurs_suspendus(app)

        audit = lire_audit_log(app)
        assert len(audit) == 1
        assert audit[0]["action"] == "utilisateurs_purges"
        assert "Ancien Suspendu" in audit[0]["detail"]
