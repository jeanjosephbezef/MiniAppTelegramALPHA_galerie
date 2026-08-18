import os


BASE_DIR = os.path.abspath(
    os.path.dirname(os.path.dirname(__file__))
)


class Config:

    # ⚠️ À changer avant la mise en production (utilise une variable d'environnement)
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-moi-plus-tard")

    # Mot de passe pour accéder à l'espace /admin
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "jatrli256")

    SQLALCHEMY_DATABASE_URI = (
        "sqlite:///" + os.path.join(BASE_DIR, "database", "app.db")
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    BASE_DIR = BASE_DIR
