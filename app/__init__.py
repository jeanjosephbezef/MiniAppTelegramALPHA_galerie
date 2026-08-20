import os

from dotenv import load_dotenv

load_dotenv()

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

from .config import Config


db = SQLAlchemy()
csrf = CSRFProtect()


def create_app():

    app = Flask(__name__)

    app.config.from_object(Config)

    # S'assure que le dossier de la base de données existe
    os.makedirs(
        os.path.join(Config.BASE_DIR, "database"),
        exist_ok=True
    )

    db.init_app(app)
    csrf.init_app(app)

    from .routes import main
    app.register_blueprint(main)

    with app.app_context():
        db.create_all()
        _migrer_colonnes_manquantes()

    return app


def _migrer_colonnes_manquantes():
    """Ajoute à chaud les colonnes créées après le premier déploiement
    (db.create_all() ne modifie jamais une table déjà existante).
    Sans Alembic, on vérifie et on ALTER TABLE si besoin — sans danger
    à rejouer, puisqu'on ne touche que les colonnes manquantes."""

    from sqlalchemy import inspect, text

    inspecteur = inspect(db.engine)

    if "produit" in inspecteur.get_table_names():
        colonnes_produit = [c["name"] for c in inspecteur.get_columns("produit")]
        with db.engine.begin() as connexion:
            if "actif" not in colonnes_produit:
                connexion.execute(
                    text("ALTER TABLE produit ADD COLUMN actif BOOLEAN DEFAULT TRUE")
                )
                connexion.execute(
                    text("UPDATE produit SET actif = TRUE WHERE actif IS NULL")
                )

    for table in ("category", "categorie_principale"):
        if table in inspecteur.get_table_names():
            colonnes = [c["name"] for c in inspecteur.get_columns(table)]
            if "ordre" not in colonnes:
                with db.engine.begin() as connexion:
                    connexion.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN ordre INTEGER DEFAULT 0")
                    )
                    connexion.execute(
                        text(f"UPDATE {table} SET ordre = 0 WHERE ordre IS NULL")
                    )

    if "parametre" not in inspecteur.get_table_names():
        return

    colonnes = [c["name"] for c in inspecteur.get_columns("parametre")]

    with db.engine.begin() as connexion:
        if "fond_ecran" not in colonnes:
            connexion.execute(
                text("ALTER TABLE parametre ADD COLUMN fond_ecran VARCHAR(255)")
            )
        if "dock_categories_actif" not in colonnes:
            connexion.execute(
                text(
                    "ALTER TABLE parametre ADD COLUMN dock_categories_actif "
                    "BOOLEAN DEFAULT 1"
                )
            )
        if "annonce_texte" not in colonnes:
            connexion.execute(
                text("ALTER TABLE parametre ADD COLUMN annonce_texte VARCHAR(255)")
            )
        if "nom_boutique" not in colonnes:
            connexion.execute(
                text("ALTER TABLE parametre ADD COLUMN nom_boutique VARCHAR(100)")
            )
        if "logo" not in colonnes:
            connexion.execute(
                text("ALTER TABLE parametre ADD COLUMN logo VARCHAR(255)")
            )
        if "couleur_accent" not in colonnes:
            connexion.execute(
                text("ALTER TABLE parametre ADD COLUMN couleur_accent VARCHAR(7)")
            )
        if "message_bienvenue" not in colonnes:
            connexion.execute(
                text(
                    "ALTER TABLE parametre ADD COLUMN message_bienvenue "
                    "VARCHAR(500)"
                )
            )