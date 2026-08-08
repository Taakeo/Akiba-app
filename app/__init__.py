from sqlalchemy import event

from config import Config

from .extensions import csrf, db, login_manager


def create_app(config_class=Config):
    from flask import Flask

    app = Flask(__name__)
    app.config.from_object(config_class)

    app.config["INSTANCE_DIR"].mkdir(parents=True, exist_ok=True)

    _configure_engine_module(app)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    with app.app_context():
        _attach_encryption_key(app)

        from .models import SubProfile  # noqa: F401 (enregistrement de tous les modèles)

        from .achats import bp as achats_bp
        from .admin import bp as admin_bp
        from .auth import bp as auth_bp
        from .caisse import bp as caisse_bp
        from .clients import bp as clients_bp
        from .factures import bp as factures_bp
        from .main import bp as main_bp
        from .pos import bp as pos_bp
        from .production import bp as production_bp
        from .rapports import bp as rapports_bp
        from .rh import bp as rh_bp
        from .stocks import bp as stocks_bp

        app.register_blueprint(auth_bp, url_prefix="/auth")
        app.register_blueprint(main_bp)
        app.register_blueprint(caisse_bp, url_prefix="/caisse")
        app.register_blueprint(pos_bp, url_prefix="/pos")
        app.register_blueprint(admin_bp, url_prefix="/admin")
        app.register_blueprint(achats_bp, url_prefix="/achats")
        app.register_blueprint(stocks_bp, url_prefix="/stocks")
        app.register_blueprint(production_bp, url_prefix="/production")
        app.register_blueprint(rh_bp, url_prefix="/rh")
        app.register_blueprint(clients_bp, url_prefix="/clients")
        app.register_blueprint(rapports_bp, url_prefix="/rapports")
        app.register_blueprint(factures_bp, url_prefix="/factures")

        db.create_all()

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(SubProfile, int(user_id))

    from .cli import register_cli

    register_cli(app)

    return app


def _configure_engine_module(app):
    """Bascule le driver SQLite sur sqlcipher3 pour chiffrer la base sur disque
    (§2.1 spec), avant la création du moteur par Flask-SQLAlchemy. Sans
    DB_ENCRYPTION_KEY (config de test en mémoire), on garde sqlite3 standard."""
    if not app.config.get("DB_ENCRYPTION_KEY"):
        return

    import sqlcipher3

    engine_options = app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", {})
    engine_options["module"] = sqlcipher3


def _attach_encryption_key(app):
    db_key = app.config.get("DB_ENCRYPTION_KEY")
    if not db_key:
        return

    key_escaped = db_key.replace("'", "''")

    @event.listens_for(db.engine, "connect")
    def _set_sqlcipher_key(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute(f"PRAGMA key = '{key_escaped}'")
        cursor.close()
