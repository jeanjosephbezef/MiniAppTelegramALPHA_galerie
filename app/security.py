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


# ==========================
# BLOCAGE AUTOMATIQUE APRÈS ÉCHECS RÉPÉTÉS
# ==========================

MAX_ECHECS = 5
FENETRE_ECHECS_SECONDES = 15 * 60  # 15 minutes
DUREE_BLOCAGE_SECONDES = 30 * 60   # 30 minutes

# En mémoire (process unique sur ce projet — voir start.py) :
# clé = identifiant (IP ou "tg:<user_id>"), valeur = liste d'horodatages d'échecs
_echecs_par_cle = {}
_blocages_temporaires = {}  # clé -> horodatage de fin de blocage


def _purger_echecs_anciens(cle):
    maintenant = time.time()
    _echecs_par_cle[cle] = [
        t for t in _echecs_par_cle.get(cle, [])
        if maintenant - t < FENETRE_ECHECS_SECONDES
    ]


def est_temporairement_bloque(cle):
    """True si cette IP/cet ID est actuellement bloqué suite à trop
    d'échecs récents. Débloque automatiquement une fois le délai passé."""
    fin_blocage = _blocages_temporaires.get(cle)
    if not fin_blocage:
        return False
    if time.time() >= fin_blocage:
        del _blocages_temporaires[cle]
        return False
    return True


def temps_restant_blocage(cle):
    fin_blocage = _blocages_temporaires.get(cle, 0)
    return max(0, int(fin_blocage - time.time()))


def enregistrer_echec(cle):
    """À appeler après un mot de passe incorrect. Bloque
    automatiquement la clé (IP ou ID Telegram) après MAX_ECHECS
    échecs dans la fenêtre de temps définie."""
    _purger_echecs_anciens(cle)
    _echecs_par_cle.setdefault(cle, []).append(time.time())

    if len(_echecs_par_cle[cle]) >= MAX_ECHECS:
        _blocages_temporaires[cle] = time.time() + DUREE_BLOCAGE_SECONDES
        _echecs_par_cle[cle] = []
        return True  # vient d'être bloqué

    return False


def reinitialiser_echecs(cle):
    """À appeler après une connexion réussie."""
    _echecs_par_cle.pop(cle, None)


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


def envoyer_alerte_telegram(texte, exclure_id=None):
    """Envoie le texte à tous les admins (ADMIN_IDS), sauf exclure_id
    si précisé — utile pour notifier "les autres admins" sans
    notifier la personne à l'origine de l'événement."""
    if not BOT_TOKEN or not ADMIN_IDS:
        return
    for admin_id in ADMIN_IDS:
        if exclure_id is not None and admin_id == exclure_id:
            continue
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={"chat_id": admin_id, "text": texte},
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

    ligne_ip = f"📍 IP : {ip}"
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


def id_est_bloque(user_id):
    """True si cet ID Telegram est dans la blacklist permanente
    (blocked_ids.json) — utilisé pour l'admin ET pour la boutique."""
    return user_id in charger_ids_bloques()


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