import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

import requests


BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Mêmes IDs que dans bot.py, lus depuis .env pour rester synchronisés
# des deux côtés sans dupliquer la liste en dur.
# Dans .env : ADMIN_TELEGRAM_IDS=8702997904,0000000000
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_TELEGRAM_IDS", "").split(",")
    if x.strip().isdigit()
}

LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "security.log")
BLOCKED_IDS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "blocked_ids.json")


def charger_ids_bloques():
    if not os.path.exists(BLOCKED_IDS_FILE):
        return set()
    try:
        with open(BLOCKED_IDS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def sauvegarder_ids_bloques(ids):
    try:
        with open(BLOCKED_IDS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(ids), f)
    except OSError as e:
        print(f"Impossible d'écrire le fichier des IDs bloqués : {e}")


def verifier_init_data(init_data, max_age_secondes=86400):
    """Vérifie la signature des données Telegram WebApp (initData).
    Retourne le dict utilisateur si la signature est valide et les
    données ne sont pas trop vieilles, sinon None."""

    if not init_data or not BOT_TOKEN:
        return None

    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    recu_hash = parsed.pop("hash", None)
    if not recu_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calcul_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calcul_hash, recu_hash):
        return None  # signature invalide -> donnée falsifiée ou mauvais token

    auth_date = int(parsed.get("auth_date", 0))
    if time.time() - auth_date > max_age_secondes:
        return None  # donnée trop ancienne, on la refuse par précaution

    user_json = parsed.get("user")
    if not user_json:
        return None

    try:
        return json.loads(user_json)
    except (ValueError, TypeError):
        return None


def obtenir_id_telegram_verifie(init_data):
    """Retourne l'ID Telegram numérique du client, extrait et vérifié à
    partir du initData envoyé par le Mini App (signature contrôlée par
    verifier_init_data). Contrairement au champ texte optionnel
    'identifiant Telegram' du formulaire de commande, cette valeur est
    fiable même si le client n'a rien saisi lui-même.
    Retourne None si initData est absent, invalide ou expiré."""

    user = verifier_init_data(init_data)
    return user.get("id") if user else None


def localiser_ip(ip):
    """Géolocalisation approximative de l'IP (pays/ville/FAI) via un
    service gratuit. Retourne None si l'IP est locale ou en cas d'échec
    (on ne bloque jamais le flux de contrôle d'accès pour ça)."""

    if not ip or ip in ("127.0.0.1", "::1", "localhost"):
        return None

    try:
        reponse = requests.get(f"https://ipapi.co/{ip}/json/", timeout=3)
        donnees = reponse.json()
    except (requests.RequestException, ValueError):
        return None

    if donnees.get("error"):
        return None

    return {
        "pays": donnees.get("country_name"),
        "ville": donnees.get("city"),
        "fai": donnees.get("org"),
    }


def journaliser_tentative(user, autorise, ip, user_agent=None, geo=None):
    ligne = {
        "horodatage": time.strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": user.get("id") if user else None,
        "username": user.get("username") if user else None,
        "prenom": user.get("first_name") if user else None,
        "nom": user.get("last_name") if user else None,
        "langue": user.get("language_code") if user else None,
        "premium": user.get("is_premium") if user else None,
        "ip": ip,
        "geo": geo,
        "user_agent": user_agent,
        "autorise": autorise,
    }
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"Impossible d'écrire dans le log de sécurité : {e}")


def envoyer_alerte_telegram(texte, bouton_texte=None, bouton_url=None):
    """Envoie le texte à tous les admins. Si bouton_texte et bouton_url
    sont fournis, ajoute un bouton inline sous le message (ex : bouton
    'Répondre' qui ouvre directement la conversation avec le client)."""

    if not BOT_TOKEN or not ADMIN_IDS:
        return

    payload = {"text": texte}

    if bouton_texte and bouton_url:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": [[{"text": bouton_texte, "url": bouton_url}]]
        })

    for admin_id in ADMIN_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={"chat_id": admin_id, **payload},
                timeout=5,
            )
        except requests.RequestException as e:
            print(f"Impossible d'envoyer l'alerte Telegram à {admin_id} : {e}")


def _construire_texte_alerte(user, ip, user_agent, geo):
    lignes = ["🚨 Tentative d'accès administrateur"]

    if user:
        nom_complet = " ".join(
            p for p in [user.get("first_name"), user.get("last_name")] if p
        ) or "inconnu"
        lignes.append(f"👤 Nom : {nom_complet}")
        lignes.append(f"📛 Username : @{user.get('username', 'inconnu')}")
        lignes.append(f"🆔 Telegram ID : {user.get('id')}")
        lignes.append(f"🌐 Langue : {user.get('language_code', 'inconnue')}")
        lignes.append(f"⭐ Premium : {'Oui' if user.get('is_premium') else 'Non'}")
    else:
        lignes.append("👤 Aucune donnée Telegram valide (accès hors Mini App ou falsifié)")

    lignes.append(f"🕐 {time.strftime('%d/%m/%Y — %H:%M')}")

    ligne_ip = f"📍 IP : {ip}" if ip else "📍 IP : non disponible (via bot Telegram)"
    if geo:
        details_geo = ", ".join(v for v in [geo.get("ville"), geo.get("pays")] if v)
        if details_geo:
            ligne_ip += f" ({details_geo})"
        if geo.get("fai"):
            ligne_ip += f"\n🛰️ FAI : {geo['fai']}"
    lignes.append(ligne_ip)

    lignes.append(f"🖥️ Appareil/navigateur : {user_agent or 'inconnu'}")
    lignes.append("🔐 Accès : REFUSÉ")

    return "\n".join(lignes)


def signaler_tentative_web(ip, user_agent, autorise):
    """Journalise + alerte (si refusé) une tentative de connexion à
    /admin/login (mot de passe web). Pas de données Telegram ici,
    seulement IP/navigateur — on géolocalise et on alerte comme pour
    le contrôle d'accès de la Mini App."""

    geo = None
    if not autorise:
        geo = localiser_ip(ip)

    journaliser_tentative(None, autorise, ip, user_agent, geo)

    if not autorise:
        envoyer_alerte_telegram(_construire_texte_alerte(None, ip, user_agent, geo))


def _utilisateur_depuis_telegram_user(u):
    """Construit un dict compatible avec journaliser_tentative/
    _construire_texte_alerte à partir d'un objet telegram.User (bot.py)."""

    if not u:
        return None

    return {
        "id": u.id,
        "username": u.username,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "language_code": u.language_code,
        "is_premium": getattr(u, "is_premium", None),
    }


def signaler_tentative_bot(telegram_user, autorise):
    """Journalise + alerte (si refusé) une tentative de connexion admin
    depuis le bot Telegram (mot de passe bot incorrect). Pas d'IP
    disponible côté bot, mais l'identité Telegram est connue."""

    user = _utilisateur_depuis_telegram_user(telegram_user)

    journaliser_tentative(user, autorise, ip=None, user_agent="Bot Telegram")

    if not autorise:
        envoyer_alerte_telegram(
            _construire_texte_alerte(user, None, "Bot Telegram", None)
        )


def controle_acces_admin(init_data, ip, user_agent=None):
    """Vérifie l'accès admin à partir des données Telegram WebApp.
    Journalise systématiquement la tentative (avec toutes les infos
    disponibles) et envoie une alerte détaillée en cas de refus.
    Retourne (autorise: bool, user: dict|None)."""

    user = verifier_init_data(init_data)
    ids_bloques = charger_ids_bloques()

    if user and user.get("id") in ids_bloques:
        autorise = False
    else:
        autorise = bool(user and user.get("id") in ADMIN_IDS)

    geo = None
    if not autorise:
        geo = localiser_ip(ip)

    journaliser_tentative(user, autorise, ip, user_agent, geo)

    if not autorise:
        envoyer_alerte_telegram(_construire_texte_alerte(user, ip, user_agent, geo))

    return autorise, user