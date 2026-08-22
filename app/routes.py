import os
import json
import requests
import hmac
import re
from functools import wraps
from datetime import datetime

import cloudinary
import cloudinary.uploader

from . import security

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    session,
    url_for,
    current_app,
    flash
)

from werkzeug.utils import secure_filename

from . import db, csrf 

from .models import (
    Produit,
    Variante,
    MediaProduit,
    TypeProduit,
    Category,
    CategoriePrincipale,
    Commande,
    ZoneLivraison,
    Parametre
)


main = Blueprint("main", __name__)


# --- Cloudinary ---
# Les identifiants viennent des variables d'environnement (voir .env / Render).
# Toutes les images/vidéos uploadées par l'admin sont envoyées vers Cloudinary
# (stockage persistant) au lieu du disque local (effacé à chaque redéploiement
# sur Render). Les images par défaut ("default.jpg") restent servies depuis
# app/static/images, car elles font partie du dépôt Git et ne changent jamais.
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True
)

CLOUDINARY_DOSSIER = "miniapp_telegram"  # dossier racine sur Cloudinary

UPLOAD_FOLDER = "app/static/images"
UPLOAD_FOLDER_VIDEOS = "app/static/videos"
EXTENSIONS_AUTORISEES = {"png", "jpg", "jpeg", "gif", "webp"}
EXTENSIONS_VIDEO_AUTORISEES = {"mp4", "mov", "webm"}


# ==========================
# OUTILS
# ==========================

def calcul_total(panier):
    return sum(item["prix"] for item in panier)


def parser_articles(produits_bruts):
    """Reconvertit le champ Commande.produits (JSON, ou ancien format
    texte Python pour les commandes créées avant ce changement) en liste
    d'articles exploitable par les templates."""

    if not produits_bruts:
        return []

    try:
        return json.loads(produits_bruts)
    except (ValueError, TypeError):
        pass

    # compatibilité avec les commandes enregistrées avant le passage au JSON
    try:
        import ast
        return ast.literal_eval(produits_bruts)
    except (ValueError, SyntaxError):
        return []


def lien_telegram(telegram_id):
    """Construit un lien cliquable vers la conversation Telegram du client,
    à partir de ce qu'il a saisi dans le champ 'identifiant Telegram' :
    - '@pseudo' ou 'pseudo' -> https://t.me/pseudo
    - un ID numérique -> tg://user?id=<id> (ouvre le profil dans l'app Telegram)
    Retourne None si rien d'exploitable n'a été saisi."""

    if not telegram_id:
        return None

    valeur = telegram_id.strip()

    if not valeur:
        return None

    if valeur.startswith("@"):
        valeur = valeur[1:]

    if valeur.isdigit():
        return f"tg://user?id={valeur}"

    return f"https://t.me/{valeur}"


def est_nouveau(produit):
    """True si le produit a été créé il y a moins de X jours (configuré
    dans Admin > Apparence > Badges produits), pour afficher le badge
    'Nouveau' sur sa fiche/carte."""
    parametre = Parametre.query.first()
    if not parametre or not parametre.badge_nouveau_actif or not produit.date_creation:
        return False
    jours = parametre.badge_nouveau_jours or 7
    return (datetime.utcnow() - produit.date_creation).days < jours


main.add_app_template_global(est_nouveau, name="est_nouveau")


def prix_affiche(valeur):
    """Formate un prix avec le symbole de devise configuré (Admin >
    Apparence > Devise), avant ou après selon le réglage."""
    parametre = Parametre.query.first()
    symbole = (parametre.devise_symbole if parametre else None) or "€"
    position = (parametre.devise_position if parametre else None) or "apres"
    valeur_formatee = f"{valeur:.2f}"
    if position == "avant":
        return f"{symbole}{valeur_formatee}"
    return f"{valeur_formatee}{symbole}"


main.add_app_template_global(prix_affiche, name="prix_affiche")


main.add_app_template_global(lien_telegram, name="lien_telegram")


def envoyer_message_telegram(chat_id, texte):
    """Envoie un message direct à un utilisateur Telegram via l'API du bot.
    Ne fonctionne de façon fiable que si chat_id est un ID numérique
    (le client doit avoir déjà démarré une conversation avec le bot,
    ce qui est garanti puisqu'il a ouvert la boutique via /start).
    Retourne True/False selon le succès de l'envoi."""

    bot_token = os.environ.get("BOT_TOKEN")

    if not bot_token or not chat_id:
        return False

    try:
        reponse = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={"chat_id": chat_id, "text": texte},
            timeout=5
        )
        return reponse.ok
    except requests.RequestException:
        return False


@main.context_processor
def injecter_apparence_globale():
    """Rend le fond d'écran configuré et la liste des catégories
    disponibles dans tous les templates, pour le dock de catégories et
    le fond d'écran personnalisé (voir base.html)."""
    return dict(
        apparence=Parametre.query.first(),
        categories_dock=Category.query.all()
    )


def media_url(nom, dossier="images"):
    """Construit l'URL d'affichage d'une image/vidéo, qu'elle vienne de
    Cloudinary (URL complète stockée en base) ou d'un fichier par défaut
    resté local dans app/static (ex: 'default.jpg'). Utiliser cette
    fonction dans les templates au lieu de url_for('static', ...) partout
    où une image/vidéo uploadée par l'admin est affichée."""

    if not nom:
        return ""
    if nom.startswith("http://") or nom.startswith("https://"):
        return nom
    return url_for("static", filename=f"{dossier}/{nom}")


main.add_app_template_global(media_url, name="media_url")


def extension_autorisee(nom_fichier):
    return (
        "." in nom_fichier
        and nom_fichier.rsplit(".", 1)[1].lower() in EXTENSIONS_AUTORISEES
    )


def extension_video_autorisee(nom_fichier):
    return (
        "." in nom_fichier
        and nom_fichier.rsplit(".", 1)[1].lower() in EXTENSIONS_VIDEO_AUTORISEES
    )


def sauvegarder_image(fichier):
    """Envoie l'image sur Cloudinary et retourne son URL complète
    (stockée telle quelle en base). Retourne 'default.jpg' si aucun
    fichier n'est fourni ou si le format n'est pas autorisé."""

    if not fichier or not fichier.filename:
        return "default.jpg"

    if not extension_autorisee(fichier.filename):
        return "default.jpg"

    resultat = cloudinary.uploader.upload(
        fichier,
        folder=f"{CLOUDINARY_DOSSIER}/images",
        resource_type="image"
    )

    return resultat["secure_url"]


def sauvegarder_video(fichier):
    """Envoie la vidéo produit sur Cloudinary si un fichier valide est
    fourni. Retourne None si aucun fichier ou format non autorisé
    (contrairement à l'image, il n'y a pas de vidéo par défaut)."""

    if not fichier or not fichier.filename:
        return None

    if not extension_video_autorisee(fichier.filename):
        return None

    resultat = cloudinary.uploader.upload(
        fichier,
        folder=f"{CLOUDINARY_DOSSIER}/videos",
        resource_type="video"
    )

    return resultat["secure_url"]


def sauvegarder_fichier_galerie(fichier, dossier, extensions_ok):
    """Comme sauvegarder_image/sauvegarder_video, pour la galerie
    photos/vidéos supplémentaires d'un produit. 'dossier' vaut
    UPLOAD_FOLDER ou UPLOAD_FOLDER_VIDEOS, utilisé ici uniquement pour
    déterminer si on envoie une image ou une vidéo à Cloudinary."""

    if not fichier or not fichier.filename:
        return None

    if not extensions_ok(fichier.filename):
        return None

    est_video = dossier == UPLOAD_FOLDER_VIDEOS
    resultat = cloudinary.uploader.upload(
        fichier,
        folder=f"{CLOUDINARY_DOSSIER}/{'videos' if est_video else 'images'}",
        resource_type="video" if est_video else "image"
    )

    return resultat["secure_url"]


def sauvegarder_medias_supplementaires(produit, fichiers):
    """Enregistre les photos et vidéos supplémentaires envoyées via les
    champs 'photos_supplementaires[]' et 'videos_supplementaires[]', et
    crée les lignes MediaProduit correspondantes (galerie de miniatures
    affichée sur la fiche produit). 'fichiers' est request.files."""

    ordre_depart = len(produit.medias)

    photos = fichiers.getlist("photos_supplementaires[]")
    for i, fichier in enumerate(photos):
        nom = sauvegarder_fichier_galerie(
            fichier, UPLOAD_FOLDER, extension_autorisee
        )
        if nom:
            db.session.add(MediaProduit(
                produit_id=produit.id,
                fichier=nom,
                type="image",
                ordre=ordre_depart + i
            ))

    videos = fichiers.getlist("videos_supplementaires[]")
    for i, fichier in enumerate(videos):
        nom = sauvegarder_fichier_galerie(
            fichier, UPLOAD_FOLDER_VIDEOS, extension_video_autorisee
        )
        if nom:
            db.session.add(MediaProduit(
                produit_id=produit.id,
                fichier=nom,
                type="video",
                ordre=ordre_depart + len(photos) + i
            ))


def supprimer_medias(form):
    """Supprime les médias de galerie cochés pour suppression dans le
    formulaire de modification ('supprimer_media[]' = liste d'ids)."""

    ids = form.getlist("supprimer_media[]")
    for media_id in ids:
        media = MediaProduit.query.get(media_id)
        if media:
            dossier = UPLOAD_FOLDER_VIDEOS if media.type == "video" else UPLOAD_FOLDER
            _supprimer_fichier_disque(dossier, media.fichier)
            db.session.delete(media)


def _extraire_public_id_cloudinary(url, est_video=False):
    """Extrait le public_id Cloudinary depuis une URL du type :
    https://res.cloudinary.com/<cloud>/image/upload/v123456/dossier/nom.jpg
    -> 'dossier/nom' (sans extension, sans version). Retourne None si
    l'URL ne correspond pas au format attendu."""

    correspondance = re.search(r"/upload/(?:v\d+/)?(.+)\.\w+$", url)
    if not correspondance:
        return None
    return correspondance.group(1)


def _supprimer_fichier_disque(dossier, nom_fichier):
    """Supprime un média Cloudinary (si nom_fichier est une URL Cloudinary)
    ou un fichier local historique (ancien système, avant migration), sans
    jamais toucher à l'image par défaut partagée par tous les
    produits/catégories sans photo."""

    if not nom_fichier or nom_fichier == "default.jpg":
        return

    if nom_fichier.startswith("http://") or nom_fichier.startswith("https://"):
        est_video = dossier == UPLOAD_FOLDER_VIDEOS
        public_id = _extraire_public_id_cloudinary(nom_fichier, est_video)
        if public_id:
            try:
                cloudinary.uploader.destroy(
                    public_id,
                    resource_type="video" if est_video else "image"
                )
            except Exception:
                pass
        return

    # Compatibilité : anciens fichiers encore présents localement
    # (uploadés avant le passage à Cloudinary)
    chemin = os.path.join(dossier, nom_fichier)
    try:
        if os.path.exists(chemin):
            os.remove(chemin)
    except OSError:
        pass


def admin_required(vue):
    @wraps(vue)
    def wrapper(*args, **kwargs):
        if not session.get("admin_connecte"):
            return redirect(url_for("main.admin_login"))
        return vue(*args, **kwargs)
    return wrapper


def sauvegarder_variantes(produit, form):
    """
    Lit les listes 'poids[]' et 'prix_variante[]' envoyées par le
    formulaire, supprime les anciennes variantes du produit et
    recrée uniquement les lignes correctement remplies.
    """

    poids_liste = form.getlist("poids[]")
    prix_liste = form.getlist("prix_variante[]")

    # On repart de zéro pour éviter les doublons lors d'une modification
    Variante.query.filter_by(produit_id=produit.id).delete()

    for poids, prix in zip(poids_liste, prix_liste):

        poids = poids.strip()
        prix = prix.strip()

        if not poids or not prix:
            continue

        try:
            prix_float = float(prix)
        except ValueError:
            continue

        variante = Variante(
            produit_id=produit.id,
            poids=poids,
            prix=prix_float
        )
        db.session.add(variante)


def sauvegarder_types(produit, form):
    """Lit la liste 'types[]' envoyée par le formulaire, supprime les
    anciens types du produit et recrée uniquement les lignes remplies."""

    noms = form.getlist("types[]")

    TypeProduit.query.filter_by(produit_id=produit.id).delete()

    for i, nom in enumerate(noms):
        nom = nom.strip()
        if not nom:
            continue
        db.session.add(TypeProduit(
            produit_id=produit.id,
            nom=nom,
            ordre=i
        ))


# ==========================
# ACCUEIL
# ==========================

@main.route("/")
def accueil():
    nouveautes = Produit.query.filter_by(actif=True).order_by(Produit.date_creation.desc()).limit(8).all()
    categories_principales = CategoriePrincipale.query.order_by(CategoriePrincipale.nom).all()
    return render_template("accueil.html", nouveautes=nouveautes, categories_principales=categories_principales)


# ==========================
# PRODUITS
# ==========================

@main.route("/produits")
def liste_produits():
    categorie_principale_filtre = request.args.get("categorie_principale", "")
    categorie_filtre = request.args.get("categorie", "")
    recherche = request.args.get("q", "").strip()

    query = Produit.query.filter_by(actif=True)

    if categorie_filtre:
        query = query.filter_by(categorie=categorie_filtre)
    elif categorie_principale_filtre:
        # aucune sous-catégorie choisie : on filtre sur toutes celles
        # de la catégorie principale sélectionnée
        noms_sous_categories = [
            c.nom for c in Category.query.filter_by(
                categorie_principale_id=categorie_principale_filtre
            ).all()
        ]
        query = query.filter(Produit.categorie.in_(noms_sous_categories))

    if recherche:
        query = query.filter(Produit.nom.ilike(f"%{recherche}%"))

    produits = query.all()

    categories_principales = CategoriePrincipale.query.order_by(CategoriePrincipale.nom).all()

    # la liste déroulante jaune (sous-catégories) ne propose que celles
    # de la catégorie principale choisie, ou toutes si aucune n'est choisie
    if categorie_principale_filtre:
        sous_categories = Category.query.filter_by(
            categorie_principale_id=categorie_principale_filtre
        ).order_by(Category.nom).all()
    else:
        sous_categories = Category.query.order_by(Category.nom).all()

    return render_template(
        "produits.html",
        produits=produits,
        categories=sous_categories,
        categories_principales=categories_principales,
        categorie_principale_filtre=categorie_principale_filtre,
        categorie_filtre=categorie_filtre,
        recherche=recherche
    )


@main.route("/produit/<int:id>")
def detail_produit(id):
    produit = Produit.query.filter_by(id=id, actif=True).first_or_404()
    return render_template("produit.html", produit=produit)


# ==========================
# CATEGORIES (PUBLIC)
# ==========================

@main.route("/categories")
def liste_categories():
    categories_principales = CategoriePrincipale.query.order_by(CategoriePrincipale.nom).all()
    return render_template("categories.html", categories_principales=categories_principales)


@main.route("/categorie-principale/<int:id>")
def categorie_principale_detail(id):
    principale = CategoriePrincipale.query.get_or_404(id)
    return render_template("categorie_principale.html", principale=principale)


@main.route("/categorie/<nom>")
def categorie(nom):
    produits = Produit.query.filter_by(categorie=nom, actif=True).all()
    return render_template("categorie.html", produits=produits, nom=nom)


# ==========================
# PANIER
# ==========================

@main.route("/ajouter/<int:id>")
def ajouter_panier(id):

    produit = Produit.query.filter_by(id=id, actif=True).first_or_404()

    # Variante optionnelle passée en paramètre : /ajouter/12?variante=3
    variante_id = request.args.get("variante")

    # Type optionnel (variété nommée) : /ajouter/12?type=4
    type_id = request.args.get("type")

    # Quantité optionnelle passée en paramètre : /ajouter/12?quantite=2
    try:
        quantite = int(request.args.get("quantite", 1))
    except ValueError:
        quantite = 1

    if quantite < 1:
        quantite = 1

    variante = None
    if variante_id and variante_id.isdigit():
        variante = Variante.query.get(int(variante_id))

    if variante:
        prix_unitaire = variante.prix
        libelle = f"{produit.nom} ({variante.poids})"
    else:
        prix_unitaire = produit.prix
        libelle = produit.nom

    if type_id and type_id.isdigit():
        type_produit = TypeProduit.query.get(int(type_id))
        if type_produit:
            libelle = f"{libelle} — {type_produit.nom}"

    panier = session.get("panier", [])

    panier.append({
        "id": produit.id,
        "nom": libelle,
        "quantite": quantite,
        "prix_unitaire": prix_unitaire,
        "prix": prix_unitaire * quantite
    })

    session["panier"] = panier

    return redirect(url_for("main.panier"))


@main.route("/panier")
def panier():
    panier = session.get("panier", [])
    return render_template(
        "panier.html",
        panier=panier,
        total=calcul_total(panier)
    )


@main.route("/panier/retirer/<int:index>")
def retirer_panier(index):
    panier = session.get("panier", [])
    if 0 <= index < len(panier):
        panier.pop(index)
        session["panier"] = panier
    return redirect(url_for("main.panier"))


@main.route("/panier/vider")
def vider_panier():
    session.pop("panier", None)
    return redirect(url_for("main.panier"))


# ==========================
# COMMANDE
# ==========================

@main.route("/commande", methods=["GET", "POST"])
def commande():

    panier = session.get("panier", [])
    total = calcul_total(panier)

    parametre = Parametre.query.first()
    zones = ZoneLivraison.query.order_by(ZoneLivraison.ville).all()

    if request.method == "POST":

        mode = request.form.get("mode")

        frais = 0
        ville = request.form.get("ville")

        if mode == "livraison":

            if parametre and total < parametre.minimum_livraison:
                return render_template(
                    "checkout.html",
                    panier=panier,
                    total=total,
                    parametre=parametre,
                    zones=zones,
                    erreur=(
                        "Livraison disponible uniquement à partir de "
                        f"{parametre.minimum_livraison:.2f} € de commande."
                    )
                )

            zone = ZoneLivraison.query.filter(
                db.func.lower(ZoneLivraison.ville) == (ville or "").strip().lower()
            ).first()

            if zone:
                frais = zone.prix

        nouvelle_commande = Commande(
            client=request.form.get("client"),
            telegram_id=request.form.get("telegram_id"),
            produits=json.dumps(panier),
            total=total + frais,
            mode_retrait=mode,
            adresse=request.form.get("adresse"),
            ville=ville if mode == "livraison" else None,
            frais_livraison=frais
        )

        db.session.add(nouvelle_commande)
        db.session.commit()

        recap = (
            "🆕 Nouvelle commande !\n"
            f"👤 {nouvelle_commande.client or 'Client inconnu'}\n"
            f"💰 Total : {nouvelle_commande.total:.2f} €\n"
            f"📦 Mode : {nouvelle_commande.mode_retrait or 'non précisé'}\n"
        )
        for item in panier:
            recap += f"  • {item.get('quantite', '?')} × {item.get('nom', 'article')}\n"
        if mode == "livraison":
            recap += f"📍 {nouvelle_commande.adresse or 'adresse non renseignée'}\n"
            recap += f"🏙️ {nouvelle_commande.ville or 'ville non renseignée'} ({frais:.2f} € de frais)\n"
        if nouvelle_commande.telegram_id:
            recap += f"💬 Répondre depuis /admin/commandes ou {lien_telegram(nouvelle_commande.telegram_id) or ''}"

        security.envoyer_alerte_telegram(recap)

        session.pop("panier", None)

        return redirect(url_for("main.confirmation"))

    return render_template(
        "checkout.html",
        panier=panier,
        total=total,
        parametre=parametre,
        zones=zones
    )


# ==========================
# CONFIRMATION
# ==========================

@main.route("/confirmation")
def confirmation():
    return render_template("confirmation.html")


# ==========================
# COMPTE
# ==========================

@main.route("/compte")
def compte():
    if session.get("admin_connecte"):
        return redirect(url_for("main.admin"))
    return render_template("compte.html")


# ==========================
# ADMIN - CONNEXION
# ==========================

@main.route("/verify-shop-access", methods=["POST"])
@csrf.exempt
def verify_shop_access():
    """Appelée automatiquement depuis chaque page de la boutique (voir
    base.html) quand elle est ouverte depuis Telegram. Vérifie si l'ID
    Telegram de la personne est dans la blacklist permanente
    (blocked_ids.json) — même liste que pour l'accès admin.

    Mémorise aussi l'ID dans la session (cookie signé) : si la personne
    rouvre ensuite le même lien hors Telegram (navigateur classique, même
    appareil), le blocage continue de s'appliquer côté serveur via
    _bloquer_blackliste_session ci-dessous."""
    init_data = request.get_json(silent=True) or {}
    user = security.verifier_init_data(init_data.get("initData", ""))

    if user and user.get("id") is not None:
        session["tg_id"] = user["id"]

    bloque = bool(user and security.id_est_bloque(user.get("id")))
    return {"blocked": bloque}


@main.before_request
def _bloquer_si_maintenance():
    """Affiche le message de maintenance à la place de la boutique quand
    le mode maintenance est activé, sauf pour l'espace admin (pour
    pouvoir le désactiver) et les fichiers statiques."""
    if (
        request.path.startswith("/admin")
        or request.path.startswith("/static")
    ):
        return

    parametre = Parametre.query.first()
    if parametre and parametre.maintenance_active:
        message = parametre.maintenance_message or "Boutique en maintenance, revenez bientôt !"
        return (
            '<div style="display:flex;align-items:center;justify-content:center;'
            'height:100vh;text-align:center;padding:24px;font-family:sans-serif;'
            'background:#111;color:#fff;">'
            f"<p>🚧 {message}</p></div>",
            503
        )


@main.before_request
def _bloquer_blackliste_session():
    """Bloque l'accès à toute page boutique pour un ID Telegram déjà
    reconnu comme blacklisté, même hors Telegram (lien ouvert dans un
    navigateur classique) — tant que le cookie de session (posé lors
    d'un premier passage via Telegram) est présent sur cet appareil.

    Ne s'applique jamais aux routes /admin/* (contrôle séparé et déjà
    plus strict), ni à /verify-shop-access elle-même, ni aux fichiers
    statiques."""
    if (
        request.path.startswith("/admin")
        or request.path == "/verify-shop-access"
        or request.path.startswith("/static")
    ):
        return

    tg_id = session.get("tg_id")
    if tg_id and security.id_est_bloque(tg_id):
        return (
            '<div style="display:flex;align-items:center;justify-content:center;'
            'height:100vh;text-align:center;padding:24px;font-family:sans-serif;">'
            "<p>⛔ Accès refusé.</p></div>",
            403,
        )


@main.route("/admin/verify-telegram", methods=["POST"])
@csrf.exempt
def verify_telegram():
    init_data = request.get_json(silent=True) or {}
    autorise, _ = security.controle_acces_admin(
        init_data.get("initData", ""),
        request.remote_addr
    )
    return {"authorized": autorise}


@main.route("/admin/login", methods=["GET", "POST"])
def admin_login():

    ip = request.headers.get("X-Forwarded-For", request.remote_addr)

    if request.method == "POST":

        if security.est_temporairement_bloque(ip):
            minutes = security.temps_restant_blocage(ip) // 60 + 1
            flash(f"Trop de tentatives échouées. Réessaie dans environ {minutes} min.")
            return render_template("admin/login.html")

        mot_de_passe = request.form.get("mot_de_passe", "")

        if hmac.compare_digest(mot_de_passe, current_app.config["ADMIN_PASSWORD"]):
            security.reinitialiser_echecs(ip)
            session.clear()
            session["admin_connecte"] = True
            session.permanent = True
            return redirect(url_for("main.admin"))

        vient_de_bloquer = security.enregistrer_echec(ip)

        user_agent = request.headers.get("User-Agent")
        geo = security.localiser_ip(ip)

        security.journaliser_tentative(None, False, ip, user_agent, geo)

        texte_alerte = (
            security._construire_texte_alerte(None, ip, user_agent, geo)
            + f"\n🔑 Mot de passe saisi (formulaire web) : {mot_de_passe}"
        )
        if vient_de_bloquer:
            texte_alerte += (
                f"\n\n⛔ IP bloquée automatiquement pendant "
                f"{security.DUREE_BLOCAGE_SECONDES // 60} minutes (trop d'échecs)."
            )
        security.envoyer_alerte_telegram(texte_alerte)

        flash("Mot de passe incorrect")

    return render_template("admin/login.html")


@main.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("main.admin_login"))


# ==========================
# ADMIN
# ==========================

@main.route("/admin")
@admin_required
def admin():

    stats = {
        "nb_produits": Produit.query.count(),
        "nb_commandes": Commande.query.count(),
        "commandes_attente": Commande.query.filter(
            Commande.statut == "En attente"
        ).count(),
    }

    dernieres_commandes = (
        Commande.query.order_by(Commande.date.desc()).limit(5).all()
    )

    for c in dernieres_commandes:
        c.articles = parser_articles(c.produits)

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        dernieres_commandes=dernieres_commandes
    )


@main.route("/admin/produits")
@admin_required
def admin_produits():

    recherche = request.args.get("q", "").strip()
    categorie_filtre = request.args.get("categorie", "").strip()
    statut_filtre = request.args.get("statut", "").strip()  # "actif" / "inactif" / ""

    requete = Produit.query

    if recherche:
        requete = requete.filter(Produit.nom.ilike(f"%{recherche}%"))

    if categorie_filtre:
        requete = requete.filter(Produit.categorie == categorie_filtre)

    if statut_filtre == "actif":
        requete = requete.filter(Produit.actif.is_(True))
    elif statut_filtre == "inactif":
        requete = requete.filter(Produit.actif.is_(False))

    produits = requete.order_by(Produit.nom).all()
    categories = Category.query.order_by(Category.nom).all()

    return render_template(
        "admin/produits.html",
        produits=produits,
        categories=categories,
        recherche=recherche,
        categorie_filtre=categorie_filtre,
        statut_filtre=statut_filtre,
    )


@main.route("/admin/produit/<int:id>/toggle-actif", methods=["POST"])
@admin_required
def toggle_actif_produit(id):
    produit = Produit.query.get_or_404(id)
    produit.actif = not produit.actif
    db.session.commit()
    flash(f"« {produit.nom} » est maintenant {'actif' if produit.actif else 'masqué'}.")
    return redirect(request.referrer or url_for("main.admin_produits"))


@main.route("/admin/produit/<int:id>/dupliquer", methods=["POST"])
@admin_required
def dupliquer_produit(id):
    original = Produit.query.get_or_404(id)

    copie = Produit(
        nom=f"{original.nom} (copie)",
        description=original.description,
        prix=original.prix,
        categorie=original.categorie,
        cbd=original.cbd,
        thc=original.thc,
        origine=original.origine,
        image=original.image,
        video=original.video,
        actif=False,  # la copie démarre masquée, le temps de l'ajuster
    )
    db.session.add(copie)
    db.session.flush()

    for v in original.variantes:
        db.session.add(Variante(produit_id=copie.id, poids=v.poids, prix=v.prix))

    for t in original.types:
        db.session.add(TypeProduit(produit_id=copie.id, nom=t.nom, ordre=t.ordre))

    # Les médias physiques (fichiers) sont réutilisés, pas recopiés sur disque
    for m in original.medias:
        db.session.add(MediaProduit(
            produit_id=copie.id, fichier=m.fichier, type=m.type, ordre=m.ordre
        ))

    db.session.commit()
    flash(f"« {original.nom} » dupliqué. Pense à modifier la copie avant de l'activer.")
    return redirect(url_for("main.modifier_produit", id=copie.id))


@main.route("/admin/commandes")
@admin_required
def admin_commandes():
    commandes = Commande.query.order_by(Commande.date.desc()).all()

    for c in commandes:
        c.articles = parser_articles(c.produits)

    return render_template("admin/commandes.html", commandes=commandes)


@main.route("/admin/commande/<int:id>/message", methods=["POST"])
@admin_required
def message_client(id):
    commande = Commande.query.get_or_404(id)
    texte = request.form.get("message", "").strip()

    if not texte:
        flash("Message vide.")
    elif not commande.telegram_id:
        flash("Ce client n'a pas d'identifiant Telegram enregistré.")
    else:
        ok = envoyer_message_telegram(
            commande.telegram_id,
            f"💬 Message de la boutique :\n\n{texte}"
        )
        if ok:
            flash("Message envoyé au client.")
        else:
            flash(
                "Échec de l'envoi — l'identifiant Telegram du client "
                "n'est peut-être pas un ID numérique valide."
            )

    return redirect(url_for("main.admin_commandes"))


@main.route("/admin/commandes/vider", methods=["POST"])
@admin_required
def vider_commandes():
    Commande.query.delete()
    db.session.commit()
    return redirect(url_for("main.admin"))


@main.route("/admin/commande/<int:id>/annuler")
@admin_required
def annuler_commande(id):
    commande = Commande.query.get_or_404(id)
    commande.statut = "Annulée"
    db.session.commit()
    return redirect(url_for("main.admin"))


@main.route("/admin/commande/<int:id>/terminer")
@admin_required
def terminer_commande(id):
    commande = Commande.query.get_or_404(id)
    commande.statut = "Terminée"
    db.session.commit()
    return redirect(url_for("main.admin"))


# ==========================
# CREATION PRODUIT
# ==========================

@main.route("/admin/produit/nouveau", methods=["GET", "POST"])
@admin_required
def nouveau_produit():

    categories = Category.query.all()
    categories_principales = CategoriePrincipale.query.order_by(CategoriePrincipale.nom).all()

    if request.method == "POST":

        produit = Produit(
            nom=request.form["nom"],
            description=request.form.get("description", "").strip() or None,
            prix=0,  # sera recalculé juste après depuis les variantes
            categorie=request.form["categorie"],
            cbd=request.form.get("cbd"),
            thc=request.form.get("thc"),
            origine=request.form.get("origine"),
            image=sauvegarder_image(request.files.get("image")),
            video=sauvegarder_video(request.files.get("video")),
            actif=bool(request.form.get("actif"))
        )

        db.session.add(produit)
        db.session.flush()  # récupère produit.id avant le commit

        sauvegarder_variantes(produit, request.form)
        sauvegarder_types(produit, request.form)
        sauvegarder_medias_supplementaires(produit, request.files)
        db.session.flush()  # pour que produit.variantes soit à jour

        if produit.variantes:
            produit.prix = min(v.prix for v in produit.variantes)

        db.session.commit()

        return redirect(url_for("main.admin_produits"))

    return render_template(
        "admin/produit_form.html",
        categories=categories,
        categories_principales=categories_principales
    )


# ==========================
# MODIFICATION PRODUIT
# ==========================

@main.route("/admin/produit/<int:id>/modifier", methods=["GET", "POST"])
@admin_required
def modifier_produit(id):

    produit = Produit.query.get_or_404(id)
    categories = Category.query.all()
    categories_principales = CategoriePrincipale.query.order_by(CategoriePrincipale.nom).all()

    if request.method == "POST":

        produit.nom = request.form["nom"]
        produit.description = request.form.get("description", "").strip() or None
        produit.categorie = request.form["categorie"]
        produit.cbd = request.form.get("cbd")
        produit.thc = request.form.get("thc")
        produit.origine = request.form.get("origine")
        produit.actif = bool(request.form.get("actif"))

        nouvelle_image = request.files.get("image")
        if nouvelle_image and nouvelle_image.filename:
            _supprimer_fichier_disque(UPLOAD_FOLDER, produit.image)
            produit.image = sauvegarder_image(nouvelle_image)
        elif request.form.get("supprimer_image"):
            _supprimer_fichier_disque(UPLOAD_FOLDER, produit.image)
            produit.image = "default.jpg"

        nouvelle_video = request.files.get("video")
        if nouvelle_video and nouvelle_video.filename:
            _supprimer_fichier_disque(UPLOAD_FOLDER_VIDEOS, produit.video)
            produit.video = sauvegarder_video(nouvelle_video)
        elif request.form.get("supprimer_video"):
            _supprimer_fichier_disque(UPLOAD_FOLDER_VIDEOS, produit.video)
            produit.video = None

        supprimer_medias(request.form)
        sauvegarder_variantes(produit, request.form)
        sauvegarder_types(produit, request.form)
        sauvegarder_medias_supplementaires(produit, request.files)
        db.session.flush()  # pour que produit.variantes soit à jour

        if produit.variantes:
            produit.prix = min(v.prix for v in produit.variantes)

        db.session.commit()

        return redirect(url_for("main.admin_produits"))

    return render_template(
        "admin/modifier_produit.html",
        produit=produit,
        categories=categories,
        categories_principales=categories_principales
    )


# ==========================
# SUPPRESSION PRODUIT
# ==========================

@main.route("/admin/produit/<int:id>/supprimer")
@admin_required
def supprimer_produit(id):

    produit = Produit.query.get_or_404(id)

    db.session.delete(produit)
    db.session.commit()

    return redirect(url_for("main.admin_produits"))


# ==========================
# ADMIN - CATEGORIES
# ==========================

@main.route("/admin/categories")
@admin_required
def admin_categories():
    categories = Category.query.order_by(Category.ordre, Category.nom).all()

    nb_produits_par_categorie = {
        cat.nom: Produit.query.filter_by(categorie=cat.nom).count()
        for cat in categories
    }

    return render_template(
        "admin/categories.html",
        categories=categories,
        nb_produits_par_categorie=nb_produits_par_categorie
    )


@main.route("/admin/categorie/nouvelle", methods=["GET", "POST"])
@admin_required
def nouvelle_categorie():

    categories_principales = CategoriePrincipale.query.order_by(CategoriePrincipale.nom).all()

    if request.method == "POST":

        nom = request.form["nom"].strip()

        doublon = Category.query.filter(db.func.lower(Category.nom) == nom.lower()).first()
        if doublon:
            flash(f"Une catégorie « {nom} » existe déjà.")
            return render_template(
                "admin/categorie_form.html",
                categories_principales=categories_principales
            )

        categorie = Category(
            nom=nom,
            image=sauvegarder_image(request.files.get("image")),
            ordre=request.form.get("ordre", type=int) or 0,
            categorie_principale_id=request.form.get("categorie_principale_id") or None
        )

        db.session.add(categorie)
        db.session.commit()

        return redirect(url_for("main.admin_categories"))

    return render_template(
        "admin/categorie_form.html",
        categories_principales=categories_principales
    )


@main.route("/admin/categorie/<int:id>/modifier", methods=["GET", "POST"])
@admin_required
def modifier_categorie(id):

    categorie = Category.query.get_or_404(id)
    categories_principales = CategoriePrincipale.query.order_by(CategoriePrincipale.nom).all()

    if request.method == "POST":

        nom = request.form["nom"].strip()

        doublon = Category.query.filter(
            db.func.lower(Category.nom) == nom.lower(), Category.id != categorie.id
        ).first()
        if doublon:
            flash(f"Une catégorie « {nom} » existe déjà.")
            return render_template(
                "admin/modifier_categorie.html",
                categorie=categorie,
                categories_principales=categories_principales
            )

        ancien_nom = categorie.nom
        categorie.nom = nom
        categorie.ordre = request.form.get("ordre", type=int) or 0
        categorie.categorie_principale_id = request.form.get("categorie_principale_id") or None

        # les produits référencent la catégorie par son nom (pas par id) :
        # on répercute le renommage pour ne pas les orpheliner
        if ancien_nom != nom:
            Produit.query.filter_by(categorie=ancien_nom).update({"categorie": nom})

        nouvelle_image = request.files.get("image")
        if nouvelle_image and nouvelle_image.filename:
            _supprimer_fichier_disque(UPLOAD_FOLDER, categorie.image)
            categorie.image = sauvegarder_image(nouvelle_image)
        elif request.form.get("supprimer_image"):
            _supprimer_fichier_disque(UPLOAD_FOLDER, categorie.image)
            categorie.image = "default.jpg"

        db.session.commit()

        return redirect(url_for("main.admin_categories"))

    return render_template(
        "admin/modifier_categorie.html",
        categorie=categorie,
        categories_principales=categories_principales
    )


@main.route("/admin/categorie/<int:id>/supprimer", methods=["POST"])
@admin_required
def supprimer_categorie(id):

    categorie = Category.query.get_or_404(id)

    nb_produits = Produit.query.filter_by(categorie=categorie.nom).count()
    if nb_produits:
        flash(
            f"Impossible de supprimer « {categorie.nom} » : {nb_produits} "
            f"produit(s) y sont encore rattaché(s). Change leur catégorie d'abord."
        )
        return redirect(url_for("main.admin_categories"))

    db.session.delete(categorie)
    db.session.commit()

    return redirect(url_for("main.admin_categories"))


# ==========================
# ADMIN - CATEGORIES PRINCIPALES
# ==========================

@main.route("/admin/categories-principales")
@admin_required
def admin_categories_principales():
    categories_principales = CategoriePrincipale.query.order_by(
        CategoriePrincipale.ordre, CategoriePrincipale.nom
    ).all()
    return render_template(
        "admin/categories_principales.html",
        categories_principales=categories_principales
    )


@main.route("/admin/categorie-principale/nouvelle", methods=["GET", "POST"])
@admin_required
def nouvelle_categorie_principale():

    if request.method == "POST":

        nom = request.form["nom"].strip()

        doublon = CategoriePrincipale.query.filter(
            db.func.lower(CategoriePrincipale.nom) == nom.lower()
        ).first()
        if doublon:
            flash(f"Une catégorie principale « {nom} » existe déjà.")
            return render_template("admin/categorie_principale_form.html")

        principale = CategoriePrincipale(
            nom=nom,
            image=sauvegarder_image(request.files.get("image")),
            ordre=request.form.get("ordre", type=int) or 0
        )

        db.session.add(principale)
        db.session.commit()

        return redirect(url_for("main.admin_categories_principales"))

    return render_template("admin/categorie_principale_form.html")


@main.route("/admin/categorie-principale/<int:id>/supprimer", methods=["POST"])
@admin_required
def supprimer_categorie_principale(id):

    principale = CategoriePrincipale.query.get_or_404(id)

    if principale.sous_categories:
        flash(
            f"Impossible de supprimer « {principale.nom} » : "
            f"{len(principale.sous_categories)} sous-catégorie(s) encore rattachée(s)."
        )
        return redirect(url_for("main.admin_categories_principales"))

    db.session.delete(principale)
    db.session.commit()

    return redirect(url_for("main.admin_categories_principales"))


# ==========================
# ADMIN - APPARENCE (fond d'écran / dock catégories)
# ==========================

@main.route("/admin/apparence", methods=["GET", "POST"])
@admin_required
def admin_apparence():

    parametre = Parametre.query.first()

    if not parametre:
        parametre = Parametre(minimum_livraison=150)
        db.session.add(parametre)
        db.session.commit()

    if request.method == "POST":

        action = request.form.get("action")

        if action == "fond":
            nouveau_fond = request.files.get("fond_ecran")
            if nouveau_fond and nouveau_fond.filename:
                parametre.fond_ecran = sauvegarder_image(nouveau_fond)
                flash("Fond d'écran mis à jour.")
            else:
                flash("Merci de choisir une image.")

        elif action == "reset_fond":
            parametre.fond_ecran = None
            flash("Fond d'écran réinitialisé par défaut.")

        elif action == "dock":
            parametre.dock_categories_actif = "dock_categories_actif" in request.form
            flash("Affichage mis à jour.")

        elif action == "annonce":
            parametre.annonce_texte = request.form.get("annonce_texte", "").strip() or None
            flash("Bandeau d'annonce mis à jour.")

        elif action == "identite":
            parametre.nom_boutique = request.form.get("nom_boutique", "").strip() or None

            nouveau_logo = request.files.get("logo")
            if nouveau_logo and nouveau_logo.filename:
                parametre.logo = sauvegarder_image(nouveau_logo)
            elif request.form.get("supprimer_logo"):
                parametre.logo = None

            flash("Identité de la boutique mise à jour.")

        elif action == "bienvenue":
            parametre.message_bienvenue = request.form.get("message_bienvenue", "").strip() or None
            flash("Message de bienvenue mis à jour.")

        elif action == "couleur":
            couleur = request.form.get("couleur_accent", "").strip()
            if not couleur:
                parametre.couleur_accent = None
                flash("Couleur d'accent réinitialisée par défaut.")
            elif len(couleur) == 7 and couleur.startswith("#"):
                parametre.couleur_accent = couleur
                flash("Couleur d'accent mise à jour.")
            else:
                flash("Couleur invalide.")

        elif action == "promo_banniere":
            parametre.promo_banniere_active = "promo_banniere_active" in request.form
            parametre.promo_banniere_texte = request.form.get("promo_banniere_texte", "").strip() or None
            couleur = request.form.get("promo_banniere_couleur", "").strip()
            if len(couleur) == 7 and couleur.startswith("#"):
                parametre.promo_banniere_couleur = couleur
            flash("Bannière promo mise à jour.")

        elif action == "badges":
            parametre.badge_nouveau_actif = "badge_nouveau_actif" in request.form
            parametre.badge_nouveau_jours = request.form.get("badge_nouveau_jours", type=int) or 7
            parametre.badge_promo_actif = "badge_promo_actif" in request.form
            flash("Badges produits mis à jour.")

        elif action == "devise":
            parametre.devise_symbole = request.form.get("devise_symbole", "").strip() or "€"
            parametre.devise_position = request.form.get("devise_position", "apres")
            flash("Devise mise à jour.")

        elif action == "footer":
            parametre.footer_actif = "footer_actif" in request.form
            parametre.footer_texte = request.form.get("footer_texte", "").strip() or None
            parametre.contact_telegram = request.form.get("contact_telegram", "").strip() or None
            flash("Pied de page mis à jour.")

        elif action == "reseaux":
            parametre.social_instagram = request.form.get("social_instagram", "").strip() or None
            parametre.social_telegram_channel = request.form.get("social_telegram_channel", "").strip() or None
            flash("Réseaux sociaux mis à jour.")

        elif action == "maintenance":
            parametre.maintenance_active = "maintenance_active" in request.form
            parametre.maintenance_message = request.form.get("maintenance_message", "").strip() or None
            flash("Mode maintenance mis à jour.")

        elif action == "css_personnalise":
            parametre.css_personnalise = request.form.get("css_personnalise", "").strip() or None
            flash("CSS personnalisé mis à jour.")

        elif action == "theme_couleurs":
            parametre.theme_mode = request.form.get("theme_mode", "dark")
            for champ, valeur_defaut in (
                ("background_color", None),
                ("couleur_secondaire", None),
                ("couleur_texte", None),
            ):
                valeur = request.form.get(champ, "").strip()
                if valeur and len(valeur) == 7 and valeur.startswith("#"):
                    setattr(parametre, champ, valeur)
                else:
                    setattr(parametre, champ, valeur_defaut)
            flash("Thème et couleurs mis à jour.")

        elif action == "typographie":
            parametre.police = request.form.get("police", "Inter")
            parametre.taille_texte_base = request.form.get("taille_texte_base", type=int) or 16
            flash("Typographie mise à jour.")

        elif action == "identite_complement":
            parametre.slogan = request.form.get("slogan", "").strip() or None
            nouvelle_banniere = request.files.get("banniere")
            if nouvelle_banniere and nouvelle_banniere.filename:
                parametre.banniere = sauvegarder_image(nouvelle_banniere)
            elif request.form.get("supprimer_banniere"):
                parametre.banniere = None
            flash("Identité complémentaire mise à jour.")

        elif action == "dock_style":
            parametre.dock_style = request.form.get("dock_style", "both")
            flash("Style du dock mis à jour.")

        elif action == "cartes":
            parametre.style_carte = request.form.get("style_carte", "rounded")
            parametre.arrondi_carte = request.form.get("arrondi_carte", type=int) or 15
            parametre.produits_par_ligne = request.form.get("produits_par_ligne", type=int) or 0
            parametre.badge_stock_actif = "badge_stock_actif" in request.form
            flash("Cartes produits mises à jour.")

        elif action == "boutons_effets":
            parametre.style_bouton = request.form.get("style_bouton", "filled")
            parametre.animations_actives = "animations_actives" in request.form
            flash("Boutons et effets mis à jour.")

        elif action == "splash":
            parametre.splash_actif = "splash_actif" in request.form
            parametre.splash_texte = request.form.get("splash_texte", "").strip() or None
            couleur = request.form.get("splash_couleur_fond", "").strip()
            if len(couleur) == 7 and couleur.startswith("#"):
                parametre.splash_couleur_fond = couleur
            parametre.splash_duree = request.form.get("splash_duree", type=int) or 1500

            nouveau_logo = request.files.get("splash_logo")
            if nouveau_logo and nouveau_logo.filename:
                parametre.splash_logo = sauvegarder_image(nouveau_logo)
            elif request.form.get("supprimer_splash_logo"):
                parametre.splash_logo = None

            flash("Écran de chargement mis à jour.")

        elif action == "reset_apparence":
            for champ in (
                "fond_ecran", "logo", "couleur_accent", "annonce_texte",
                "nom_boutique", "message_bienvenue",
                "promo_banniere_active", "promo_banniere_texte", "promo_banniere_couleur",
                "badge_nouveau_actif", "badge_nouveau_jours", "badge_promo_actif",
                "devise_symbole", "devise_position",
                "footer_actif", "footer_texte", "contact_telegram",
                "social_instagram", "social_telegram_channel",
                "maintenance_active", "maintenance_message", "css_personnalise",
                "theme_mode", "background_color", "couleur_secondaire", "couleur_texte",
                "police", "taille_texte_base", "slogan", "banniere",
                "dock_style", "style_carte", "arrondi_carte", "produits_par_ligne",
                "badge_stock_actif", "style_bouton", "animations_actives",
                "splash_actif", "splash_logo", "splash_texte", "splash_couleur_fond", "splash_duree",
            ):
                setattr(parametre, champ, Parametre.__table__.columns[champ].default.arg
                        if Parametre.__table__.columns[champ].default is not None else None)
            flash("Toute la personnalisation a été réinitialisée par défaut.")

        db.session.commit()

        return redirect(url_for("main.admin_apparence"))

    return render_template("admin/apparence.html", parametre=parametre)


@main.route("/admin/dock/reordonner", methods=["POST"])
@admin_required
@csrf.exempt
def admin_dock_reordonner():
    """Reçoit la nouvelle liste d'IDs de catégories dans l'ordre choisi
    par glisser-déposer (Admin > Apparence > Dock catégories) et met à
    jour Category.ordre en conséquence. Appelé en AJAX depuis le JS de
    la page apparence — répond en JSON."""

    donnees = request.get_json(silent=True) or {}
    ids_ordonnes = donnees.get("ordre", [])

    for position, cat_id in enumerate(ids_ordonnes):
        categorie = Category.query.get(cat_id)
        if categorie:
            categorie.ordre = position

    db.session.commit()
    return {"success": True}


# ==========================
# ADMIN - LIVRAISON
# ==========================

@main.route("/admin/livraison")
@admin_required
def admin_livraison():
    zones = ZoneLivraison.query.order_by(ZoneLivraison.ville).all()
    parametre = Parametre.query.first()

    if not parametre:
        parametre = Parametre(minimum_livraison=150)
        db.session.add(parametre)
        db.session.commit()

    return render_template(
        "admin/livraison.html",
        zones=zones,
        parametre=parametre
    )


@main.route("/admin/livraison/minimum", methods=["POST"])
@admin_required
def modifier_minimum_livraison():
    parametre = Parametre.query.first()

    if not parametre:
        parametre = Parametre()
        db.session.add(parametre)

    try:
        parametre.minimum_livraison = float(request.form.get("minimum_livraison", 0))
    except ValueError:
        parametre.minimum_livraison = 0

    db.session.commit()

    return redirect(url_for("main.admin_livraison"))


@main.route("/admin/livraison/zone/nouvelle", methods=["POST"])
@admin_required
def nouvelle_zone_livraison():

    ville = request.form.get("ville", "").strip()

    try:
        prix = float(request.form["prix"])
    except (ValueError, KeyError):
        flash("Merci de remplir correctement la ville et le prix.")
        return redirect(url_for("main.admin_livraison"))

    if not ville:
        flash("Merci de remplir correctement la ville et le prix.")
        return redirect(url_for("main.admin_livraison"))

    zone_existante = ZoneLivraison.query.filter_by(ville=ville).first()
    if zone_existante:
        zone_existante.prix = prix
    else:
        db.session.add(ZoneLivraison(ville=ville, prix=prix))

    db.session.commit()

    return redirect(url_for("main.admin_livraison"))


@main.route("/admin/livraison/zone/<int:id>/supprimer")
@admin_required
def supprimer_zone_livraison(id):
    zone = ZoneLivraison.query.get_or_404(id)
    db.session.delete(zone)
    db.session.commit()
    return redirect(url_for("main.admin_livraison"))