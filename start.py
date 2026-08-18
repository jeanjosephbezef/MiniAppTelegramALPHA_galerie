"""
Point d'entrée unique pour Render : lance le bot Telegram en tâche de
fond (polling) ET le serveur Flask dans le même processus, sur le même
service web.

Commande de démarrage à mettre dans Render :
    python start.py
"""

import os
import threading

from app import create_app
import bot as bot_module


def lancer_bot():
    """Lance le bot Telegram (polling) dans un thread séparé."""
    bot_module.main()


if __name__ == "__main__":

    # Le bot tourne dans un thread daemon : il s'arrête automatiquement
    # si le processus principal (Flask) s'arrête.
    thread_bot = threading.Thread(target=lancer_bot, daemon=True)
    thread_bot.start()

    app = create_app()

    # Render fournit le port à écouter via la variable d'environnement PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)