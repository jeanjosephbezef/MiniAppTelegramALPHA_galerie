import os
from datetime import timedelta


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

    # --- Sécurité de session admin ---
    # HTTPONLY empêche le JS de lire le cookie de session (protection XSS)
    SESSION_COOKIE_HTTPONLY = True
    # SECURE : le cookie n'est envoyé qu'en HTTPS. Mets False en local
    # (http://127.0.0.1) via la variable d'env, True en production (Render).
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV") != "development"
    # SAMESITE=Lax bloque l'usage du cookie depuis un autre site
    SESSION_COOKIE_SAMESITE = "Lax"
    # Déconnexion automatique après 30 minutes d'inactivité
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    SESSION_REFRESH_EACH_REQUEST = True