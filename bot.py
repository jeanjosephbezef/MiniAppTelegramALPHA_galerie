import os

from dotenv import load_dotenv

load_dotenv()

from telegram import (
    Update,
    WebAppInfo,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
    MenuButtonCommands,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import json
import ast
import hmac
import time

# accès aux modèles Flask/SQLAlchemy pour lire et corriger les commandes,
# et au module de sécurité partagé avec le site (mêmes logs, mêmes alertes)
from app import create_app, db as flask_db, security
from app.models import Commande, ZoneLivraison, Parametre

MESSAGE_BIENVENUE_DEFAUT = (
    "Bienvenue 🌿\n\nAppuyez sur le bouton ci-dessous pour ouvrir la boutique."
)


def _message_bienvenue() -> str:
    """Retourne le message de bienvenue configuré depuis Admin > Apparence,
    ou le message par défaut si rien n'a été renseigné."""
    with flask_app.app_context():
        parametre = Parametre.query.first()
        if parametre and parametre.message_bienvenue:
            return parametre.message_bienvenue
    return MESSAGE_BIENVENUE_DEFAUT

flask_app = create_app()


def _parser_articles(produits_bruts):
    """Reconvertit Commande.produits (JSON, ou ancien format texte Python)
    en liste d'articles affichable dans le bot."""
    if not produits_bruts:
        return []
    try:
        return json.loads(produits_bruts)
    except (ValueError, TypeError):
        pass
    try:
        return ast.literal_eval(produits_bruts)
    except (ValueError, SyntaxError):
        return []


BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBAPP_URL = os.environ.get("WEBAPP_URL")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")       # mot de passe pour la page web /admin/login
BOT_ADMIN_PASSWORD = os.environ.get("BOT_ADMIN_PASSWORD")  # mot de passe pour la reconnaissance dans le bot

# Mot de passe "piège" : s'il est entré à la place du vrai mot de passe admin,
# l'ID Telegram est immédiatement et définitivement blacklisté (fichier
# blocked_ids.json, partagé avec le contrôle d'accès de l'admin web).
# Optionnel : si BOT_TRAP_PASSWORD n'est pas défini dans .env, cette
# fonctionnalité est simplement désactivée.
BOT_TRAP_PASSWORD = os.environ.get("BOT_TRAP_PASSWORD")

# IDs Telegram autorisés à accéder à l'espace admin, lus depuis .env
# (ADMIN_TELEGRAM_IDS=8702997904,0000000000) pour rester synchronisés
# avec app/security.py sans dupliquer la liste en dur à deux endroits.
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_TELEGRAM_IDS", "").split(",")
    if x.strip().isdigit()
}


def _track(context: ContextTypes.DEFAULT_TYPE, message_id: int):
    """Garde en mémoire les messages envoyés/reçus pendant la session pour pouvoir les supprimer."""
    context.user_data.setdefault("session_message_ids", []).append(message_id)


def _user_dict(update: Update) -> dict:
    """Convertit l'utilisateur Telegram de update en dict, au même format
    que celui attendu par app/security.py (issu de initData côté web)."""
    user = update.effective_user
    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "language_code": user.language_code,
        "is_premium": getattr(user, "is_premium", None),
    }


def _notifier_intrusion(update: Update, autorise: bool = False):
    """Journalise la tentative dans security.log et envoie l'alerte
    Telegram habituelle — même format que pour les tentatives via le
    site web, pour un historique unifié. Si la personne à l'origine
    de la tentative est elle-même un admin (ex: mauvais mot de passe
    tapé par erreur), elle n'est jamais notifiée de sa propre
    tentative — seuls les autres admins le sont."""
    user_dict = _user_dict(update)
    security.journaliser_tentative(
        user_dict, autorise, ip=None, user_agent="Bot Telegram"
    )
    texte = security._construire_texte_alerte(
        user_dict, ip="(via bot Telegram)", user_agent=None, geo=None
    )
    security.envoyer_alerte_telegram(texte, exclure_id=update.effective_user.id)


def _notifier_connexion_admin(update: Update):
    """Prévient l'AUTRE admin (pas celui qui vient de se connecter)
    qu'un accès admin réussi vient d'avoir lieu via /admin."""
    user = update.effective_user
    nom_complet = " ".join(p for p in [user.first_name, user.last_name] if p) or "inconnu"
    texte = (
        "🔓 Connexion admin réussie\n"
        f"👤 Nom : {nom_complet}\n"
        f"📛 Username : @{user.username or 'inconnu'}\n"
        f"🆔 Telegram ID : {user.id}\n"
        f"🕐 {time.strftime('%d/%m/%Y — %H:%M')}"
    )
    security.envoyer_alerte_telegram(texte, exclure_id=user.id)


def _est_blackliste(user_id: int) -> bool:
    """True si cet ID Telegram a été blacklisté définitivement
    (via blocked_ids.json), y compris s'il figure dans ADMIN_IDS."""
    return user_id in security.charger_ids_bloques()


def _blacklister_id(user_id: int):
    """Ajoute un ID Telegram à blocked_ids.json de façon permanente.
    Ce blocage est partagé avec l'admin web (controle_acces_admin) :
    la personne perd aussi l'accès à /admin/login même si elle
    connaît ADMIN_PASSWORD."""
    ids_bloques = security.charger_ids_bloques()
    ids_bloques.add(user_id)
    security.sauvegarder_ids_bloques(ids_bloques)


def _debloquer_id(user_id: int):
    """Retire un ID Telegram de blocked_ids.json. Redonne l'accès
    partout (bot + admin web) s'il s'agit d'un ID admin reconnu."""
    ids_bloques = security.charger_ids_bloques()
    ids_bloques.discard(user_id)
    security.sauvegarder_ids_bloques(ids_bloques)


async def _alerter_avec_choix(context: ContextTypes.DEFAULT_TYPE, update: Update, entete: str):
    """Envoie à chaque admin une alerte avec deux boutons pour décider,
    au cas par cas, de blacklister ou d'ignorer l'ID à l'origine de
    l'événement. Ne blackliste rien automatiquement — utilisée aussi
    bien pour le mot de passe piège que pour un /admin tapé par un
    utilisateur non reconnu."""
    user_dict = _user_dict(update)
    cible_id = update.effective_user.id

    security.journaliser_tentative(
        user_dict, autorise=False, ip=None, user_agent="Bot Telegram"
    )

    texte = entete + "\n\n" + security._construire_texte_alerte(
        user_dict, ip="(via bot Telegram)", user_agent=None, geo=None
    )

    clavier = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⛔ Blacklister", callback_data=f"piege_blacklist:{cible_id}"),
            InlineKeyboardButton("✅ Ignorer", callback_data=f"piege_ignorer:{cible_id}"),
        ]
    ])

    if not BOT_TOKEN or not ADMIN_IDS:
        return
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id, text=texte, reply_markup=clavier
            )
        except Exception as e:
            print(f"Impossible d'envoyer l'alerte à {admin_id} : {e}")


async def _alerter_piege_declenche(context: ContextTypes.DEFAULT_TYPE, update: Update):
    """Cas particulier de _alerter_avec_choix : mot de passe piège tapé
    dans le flux /admin."""
    await _alerter_avec_choix(
        context, update, "🪤 PIÈGE DÉCLENCHÉ — mot de passe piège utilisé"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _track(context, update.message.message_id)

    # /start ouvre toujours directement la boutique, admin ou pas
    clavier = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            text="🛍️ Ouvrir la boutique",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )]
    ])

    msg = await update.message.reply_text(
        _message_bienvenue(),
        reply_markup=clavier
    )
    _track(context, msg.message_id)


async def handle_admin_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # on ne traite ce message que si on attend un mot de passe admin de cet utilisateur
    if not context.user_data.get("awaiting_admin_password"):
        return False

    context.user_data["awaiting_admin_password"] = False

    cle_blocage = f"tg:{update.effective_user.id}"

    if _est_blackliste(update.effective_user.id):
        # ID blacklisté définitivement (ex: piège déjà déclenché) : on
        # continue de répondre comme si le mot de passe était faux, sans
        # jamais révéler que ce compte est bloqué de façon permanente.
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )
        except Exception:
            pass
        _notifier_intrusion(update, autorise=False)
        msg = await update.message.reply_text(
            "❌ Mot de passe incorrect. Retape /admin pour réessayer."
        )
        _track(context, msg.message_id)
        return True

    if security.est_temporairement_bloque(cle_blocage):
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )
        except Exception:
            pass
        minutes = security.temps_restant_blocage(cle_blocage) // 60 + 1
        msg = await update.message.reply_text(
            f"⛔ Trop de tentatives échouées. Réessaie dans environ {minutes} min."
        )
        _track(context, msg.message_id)
        return True

    password_ok = hmac.compare_digest(update.message.text.strip(), BOT_ADMIN_PASSWORD)
    piege_ok = bool(BOT_TRAP_PASSWORD) and hmac.compare_digest(
        update.message.text.strip(), BOT_TRAP_PASSWORD
    )

    # supprime le message contenant le mot de passe pour qu'il n'apparaisse pas dans le chat
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id,
        )
    except Exception as e:
        print(f"Impossible de supprimer le message du mot de passe : {e}")

    if piege_ok:
        # mot de passe piège : on n'auto-blackliste PAS, on prévient les
        # admins avec un bouton pour décider au cas par cas — sans jamais
        # laisser deviner à la personne que c'était un piège plutôt
        # qu'une simple erreur.
        await _alerter_piege_declenche(context, update)
        msg = await update.message.reply_text(
            "❌ Mot de passe incorrect. Retape /admin pour réessayer."
        )
        _track(context, msg.message_id)
        return True

    if password_ok:
        security.reinitialiser_echecs(cle_blocage)
        _notifier_connexion_admin(update)
        clavier = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                text="🔐 Ouvrir l'admin",
                web_app=WebAppInfo(url=f"{WEBAPP_URL}/admin/login")
            )],
        ])
        msg = await update.message.reply_text(
            "✅ Accès admin validé.",
            reply_markup=clavier
        )
        _track(context, msg.message_id)
    else:
        vient_de_bloquer = security.enregistrer_echec(cle_blocage)
        _notifier_intrusion(update, autorise=False)
        texte = "❌ Mot de passe incorrect. Retape /admin pour réessayer."
        if vient_de_bloquer:
            texte = "⛔ Trop de tentatives échouées. Accès bloqué temporairement."
        msg = await update.message.reply_text(texte)
        _track(context, msg.message_id)

    return True


async def handle_correction_ville(update: Update, context: ContextTypes.DEFAULT_TYPE):
    commande_id = context.user_data.get("correction_ville_commande_id")
    if not commande_id:
        return False

    context.user_data["correction_ville_commande_id"] = None
    nouvelle_ville = update.message.text.strip()

    with flask_app.app_context():
        commande = Commande.query.get(commande_id)

        if not commande:
            msg = await update.message.reply_text("⚠️ Commande introuvable (peut-être déjà supprimée).")
            _track(context, msg.message_id)
            return True

        zone = ZoneLivraison.query.filter(
            flask_db.func.lower(ZoneLivraison.ville) == nouvelle_ville.lower()
        ).first()

        ancien_frais = commande.frais_livraison or 0
        nouveau_frais = zone.prix if zone else 0

        commande.ville = nouvelle_ville
        commande.frais_livraison = nouveau_frais
        commande.total = (commande.total or 0) - ancien_frais + nouveau_frais

        db_session = flask_db.session
        db_session.commit()

        if zone:
            texte = (
                f"✅ Ville mise à jour : {nouvelle_ville}\n"
                f"🚚 Frais de livraison : {nouveau_frais:.2f} €\n"
                f"💰 Nouveau total : {commande.total:.2f} €"
            )
        else:
            texte = (
                f"✅ Ville enregistrée : {nouvelle_ville}\n"
                f"⚠️ Aucune zone configurée pour cette ville — 0 € de frais appliqués.\n"
                f"💰 Total inchangé : {commande.total:.2f} €"
            )

    msg = await update.message.reply_text(texte)
    _track(context, msg.message_id)
    return True


async def dispatch_texte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Un seul point d'entrée pour tous les messages texte simples,
    pour éviter que deux logiques (mot de passe / correction de ville)
    ne se marchent dessus."""

    if await handle_admin_password(update, context):
        return

    if await handle_correction_ville(update, context):
        return

    if await handle_reponse_client(update, context):
        return


async def commandes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /commandes — réservée aux admins reconnus.
    Liste les commandes en attente avec le détail meet up / livraison,
    et propose de corriger la ville quand elle manque."""

    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        _notifier_intrusion(update, autorise=False)
        return  # silence total pour un utilisateur non admin

    with flask_app.app_context():
        liste = (
            Commande.query
            .filter_by(statut="En attente")
            .order_by(Commande.date.desc())
            .limit(15)
            .all()
        )

        if not liste:
            msg = await update.message.reply_text("Aucune commande en attente pour le moment.")
            _track(context, msg.message_id)
            return

        for c in liste:

            texte = (
                f"👤 {c.client or 'Client inconnu'}\n"
                f"💰 Total : {c.total:.2f} €\n"
                f"📦 Mode : {c.mode_retrait or 'non précisé'}\n"
            )

            articles = _parser_articles(c.produits)
            if articles:
                texte += "🛒 Articles :\n"
                for a in articles:
                    texte += f"  • {a.get('quantite', '?')} × {a.get('nom', 'article')}\n"

            clavier = None
            boutons = []

            if c.mode_retrait == "livraison":
                texte += f"📍 Adresse : {c.adresse or 'non renseignée'}\n"
                texte += f"🏙️ Ville : {c.ville or 'non renseignée'}\n"
                texte += f"🚚 Frais appliqués : {(c.frais_livraison or 0):.2f} €"

                if not c.ville:
                    boutons.append([InlineKeyboardButton(
                        "✏️ Renseigner / corriger la ville",
                        callback_data=f"corriger_ville:{c.id}"
                    )])

            if c.telegram_id:
                boutons.append([InlineKeyboardButton(
                    "✉️ Répondre au client",
                    callback_data=f"repondre_client:{c.id}"
                )])

            if boutons:
                clavier = InlineKeyboardMarkup(boutons)

            msg = await update.message.reply_text(texte, reply_markup=clavier)
            _track(context, msg.message_id)

    _track(context, update.message.message_id)


async def corriger_ville_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        return

    commande_id = int(query.data.split(":")[1])
    context.user_data["correction_ville_commande_id"] = commande_id

    msg = await query.message.reply_text("Tape le nom de la ville pour cette commande :")
    _track(context, msg.message_id)


async def repondre_client_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        return

    commande_id = int(query.data.split(":")[1])
    context.user_data["repondre_client_commande_id"] = commande_id

    msg = await query.message.reply_text("Tape le message à envoyer au client :")
    _track(context, msg.message_id)


async def piege_decision_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Traite le clic sur ⛔ Blacklister / ✅ Ignorer envoyé après le
    déclenchement du mot de passe piège."""
    query = update.callback_query

    if query.from_user.id not in ADMIN_IDS:
        await query.answer("Réservé aux admins.", show_alert=True)
        return

    action, cible_id_str = query.data.split(":")
    cible_id = int(cible_id_str)

    if action == "piege_blacklist":
        _blacklister_id(cible_id)
        await query.answer("ID blacklisté.")
        await query.edit_message_text(
            query.message.text + f"\n\n⛔ Blacklisté par {query.from_user.first_name}."
        )
    else:  # piege_ignorer
        await query.answer("Ignoré.")
        await query.edit_message_text(
            query.message.text + f"\n\n✅ Ignoré par {query.from_user.first_name}."
        )


async def handle_reponse_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    commande_id = context.user_data.get("repondre_client_commande_id")
    if not commande_id:
        return False

    context.user_data["repondre_client_commande_id"] = None
    texte_message = update.message.text.strip()

    with flask_app.app_context():
        commande = Commande.query.get(commande_id)

        if not commande or not commande.telegram_id:
            msg = await update.message.reply_text("⚠️ Commande introuvable ou client sans identifiant Telegram.")
            _track(context, msg.message_id)
            return True

        chat_id_client = commande.telegram_id

    try:
        await context.bot.send_message(
            chat_id=chat_id_client,
            text=f"💬 Message de la boutique :\n\n{texte_message}"
        )
        msg = await update.message.reply_text("✅ Message envoyé au client.")
    except Exception as e:
        msg = await update.message.reply_text(
            f"❌ Échec de l'envoi (le client a peut-être bloqué le bot, ou l'ID n'est pas valide) : {e}"
        )

    _track(context, msg.message_id)
    return True


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /admin — ne répond QUE si l'utilisateur est un ID admin reconnu
    et non blacklisté. Pour tout autre utilisateur, le bot ignore totalement
    la commande (aucune réponse)."""
    user_id = update.effective_user.id

    if _est_blackliste(user_id):
        _notifier_intrusion(update, autorise=False)
        return  # silence total, décision déjà prise (blacklisté)

    if user_id not in ADMIN_IDS:
        await _alerter_avec_choix(
            context, update,
            "🚫 /admin tapé par un utilisateur non reconnu"
        )
        return  # silence total côté chat, pas d'indice que /admin existe

    # même comportement que /start pour un admin : redemande le mot de passe
    context.user_data["awaiting_admin_password"] = True
    msg = await update.message.reply_text(
        "Vérification d'identité"
    )
    _track(context, update.message.message_id)
    _track(context, msg.message_id)


async def debloquer_liste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /debloquer — réservée aux admins non blacklistés.
    Liste les IDs actuellement blacklistés avec un bouton pour
    retirer chacun d'eux de blocked_ids.json."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS or _est_blackliste(user_id):
        return  # silence total, comme /admin

    ids_bloques = sorted(security.charger_ids_bloques())

    if not ids_bloques:
        msg = await update.message.reply_text("✅ Aucun ID actuellement blacklisté.")
        _track(context, update.message.message_id)
        _track(context, msg.message_id)
        return

    boutons = [
        [InlineKeyboardButton(f"✅ Débloquer {bid}", callback_data=f"debloquer:{bid}")]
        for bid in ids_bloques
    ]
    msg = await update.message.reply_text(
        "⛔ IDs actuellement blacklistés :",
        reply_markup=InlineKeyboardMarkup(boutons),
    )
    _track(context, update.message.message_id)
    _track(context, msg.message_id)


async def debloquer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.from_user.id not in ADMIN_IDS:
        await query.answer("Réservé aux admins.", show_alert=True)
        return

    cible_id = int(query.data.split(":")[1])
    _debloquer_id(cible_id)
    await query.answer(f"{cible_id} débloqué.")
    await query.edit_message_text(
        query.message.text + f"\n\n✅ {cible_id} débloqué par {query.from_user.first_name}."
    )


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Supprime tous les messages échangés pendant la session en cours."""
    message_ids = context.user_data.get("session_message_ids", [])

    # on supprime aussi le message /logout lui-même
    message_ids.append(update.message.message_id)

    deleted = 0
    for msg_id in message_ids:
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=msg_id,
            )
            deleted += 1
        except Exception:
            pass  # message déjà supprimé, trop vieux (>48h), ou introuvable

    context.user_data["session_message_ids"] = []

    confirmation = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🧹 Historique de session nettoyé ({deleted} message(s) supprimé(s))."
    )
    # ce message de confirmation se supprime tout seul après quelques secondes
    context.job_queue.run_once(
        lambda ctx: ctx.bot.delete_message(chat_id=update.effective_chat.id, message_id=confirmation.message_id),
        when=5,
    )


async def _configuration_initiale(app):
    """Retire le bouton menu personnalisé (raccourci vers la mini-app) et
    ne laisse que /start visible dans le menu de commandes du bot."""

    # remet le bouton menu au comportement standard (liste de commandes),
    # au lieu d'un bouton dédié qui ouvrirait la mini-app directement
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    # seule /start apparaît dans le menu "/" — /admin, /commandes et /logout
    # restent fonctionnelles si on les tape, mais ne sont pas suggérées
    await app.bot.set_my_commands([
        BotCommand("start", "Démarrer"),
    ])


def main():

    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN manquant dans le fichier .env")

    if not WEBAPP_URL:
        raise ValueError("WEBAPP_URL manquant dans le fichier .env")

    if not ADMIN_PASSWORD:
        raise ValueError("ADMIN_PASSWORD manquant dans le fichier .env")

    if not BOT_ADMIN_PASSWORD:
        raise ValueError("BOT_ADMIN_PASSWORD manquant dans le fichier .env")

    if not ADMIN_IDS:
        raise ValueError(
            "ADMIN_TELEGRAM_IDS manquant ou vide dans le fichier .env "
            "(ex: ADMIN_TELEGRAM_IDS=8702997904,0000000000)"
        )

    app = Application.builder().token(BOT_TOKEN).post_init(_configuration_initiale).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("commandes", commandes))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("debloquer", debloquer_liste))
    app.add_handler(CallbackQueryHandler(corriger_ville_callback, pattern=r"^corriger_ville:\d+$"))
    app.add_handler(CallbackQueryHandler(repondre_client_callback, pattern=r"^repondre_client:\d+$"))
    app.add_handler(CallbackQueryHandler(piege_decision_callback, pattern=r"^piege_(blacklist|ignorer):\d+$"))
    app.add_handler(CallbackQueryHandler(debloquer_callback, pattern=r"^debloquer:\d+$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, dispatch_texte))

    print("Bot démarré, en attente de messages...")
    # stop_signals=None : nécessaire pour pouvoir lancer le bot depuis un
    # thread secondaire (voir start.py) — la gestion des signaux système
    # (Ctrl+C) ne fonctionne que dans le thread principal.
    app.run_polling(stop_signals=None)


if __name__ == "__main__":
    main()