import os
import json
import requests
import hmac
from functools import wraps

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

    if not fichier or not fichier.filename:
        return "default.jpg"

    if not extension_autorisee(fichier.filename):
        # Type de fichier non autorisé -> image par défaut
        return "default.jpg"

    nom = secure_filename(fichier.filename)

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    chemin = os.path.join(UPLOAD_FOLDER, nom)

    fichier.save(chemin)

    return nom


def sauvegarder_video(fichier):
    """Enregistre la vidéo produit si un fichier valide est fourni.
    Retourne None si aucun fichier ou format non autorisé (contrairement
    à l'image, il n'y a pas de vidéo par défaut)."""

    if not fichier or not fichier.filename:
        return None

    if not extension_video_autorisee(fichier.filename):
        return None

    nom = secure_filename(fichier.filename)

    os.makedirs(UPLOAD_FOLDER_VIDEOS, exist_ok=True)

    chemin = os.path.join(UPLOAD_FOLDER_VIDEOS, nom)

    fichier.save(chemin)

    return nom


def sauvegarder_fichier_galerie(fichier, dossier, extensions_ok):
    """Comme sauvegarder_image/sauvegarder_video, mais préfixe le nom du
    fichier pour éviter qu'un envoi multiple (plusieurs photos/vidéos
    d'un coup) n'écrase un fichier existant portant le même nom."""

    if not fichier or not fichier.filename:
        return None

    if not extensions_ok(fichier.filename):
        return None

    import uuid
    nom = f"{uuid.uuid4().hex[:8]}_{secure_filename(fichier.filename)}"

    os.makedirs(dossier, exist_ok=True)
    fichier.save(os.path.join(dossier, nom))

    return nom


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


def _supprimer_fichier_disque(dossier, nom_fichier):
    """Supprime un fichier du disque s'il existe, sans jamais toucher à
    l'image par défaut (partagée par tous les produits/catégories sans photo)."""

    if not nom_fichier or nom_fichier == "default.jpg":
        return

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
    nouveautes = Produit.query.order_by(Produit.date_creation.desc()).limit(8).all()
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

    query = Produit.query

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
    produit = Produit.query.get_or_404(id)
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
    produits = Produit.query.filter_by(categorie=nom).all()
    return render_template("categorie.html", produits=produits, nom=nom)


# ==========================
# PANIER
# ==========================

@main.route("/ajouter/<int:id>")
def ajouter_panier(id):

    produit = Produit.query.get_or_404(id)

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
    (blocked_ids.json) — même liste que pour l'accès admin."""
    init_data = request.get_json(silent=True) or {}
    user = security.verifier_init_data(init_data.get("initData", ""))

    bloque = bool(user and security.id_est_bloque(user.get("id")))
    return {"blocked": bloque}


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
    produits = Produit.query.all()
    return render_template("admin/produits.html", produits=produits)


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
            description=request.form["description"],
            prix=0,  # sera recalculé juste après depuis les variantes
            categorie=request.form["categorie"],
            cbd=request.form.get("cbd"),
            thc=request.form.get("thc"),
            origine=request.form.get("origine"),
            image=sauvegarder_image(request.files.get("image")),
            video=sauvegarder_video(request.files.get("video"))
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
        produit.description = request.form["description"]
        produit.categorie = request.form["categorie"]
        produit.cbd = request.form.get("cbd")
        produit.thc = request.form.get("thc")
        produit.origine = request.form.get("origine")

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
    categories = Category.query.all()
    return render_template("admin/categories.html", categories=categories)


@main.route("/admin/categorie/nouvelle", methods=["GET", "POST"])
@admin_required
def nouvelle_categorie():

    categories_principales = CategoriePrincipale.query.order_by(CategoriePrincipale.nom).all()

    if request.method == "POST":

        categorie = Category(
            nom=request.form["nom"],
            image=sauvegarder_image(request.files.get("image")),
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

        categorie.nom = request.form["nom"]
        categorie.categorie_principale_id = request.form.get("categorie_principale_id") or None

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


@main.route("/admin/categorie/<int:id>/supprimer")
@admin_required
def supprimer_categorie(id):

    categorie = Category.query.get_or_404(id)

    db.session.delete(categorie)
    db.session.commit()

    return redirect(url_for("main.admin_categories"))


# ==========================
# ADMIN - CATEGORIES PRINCIPALES
# ==========================

@main.route("/admin/categories-principales")
@admin_required
def admin_categories_principales():
    categories_principales = CategoriePrincipale.query.order_by(CategoriePrincipale.nom).all()
    return render_template(
        "admin/categories_principales.html",
        categories_principales=categories_principales
    )


@main.route("/admin/categorie-principale/nouvelle", methods=["GET", "POST"])
@admin_required
def nouvelle_categorie_principale():

    if request.method == "POST":

        principale = CategoriePrincipale(
            nom=request.form["nom"],
            image=sauvegarder_image(request.files.get("image"))
        )

        db.session.add(principale)
        db.session.commit()

        return redirect(url_for("main.admin_categories_principales"))

    return render_template("admin/categorie_principale_form.html")


@main.route("/admin/categorie-principale/<int:id>/supprimer")
@admin_required
def supprimer_categorie_principale(id):

    principale = CategoriePrincipale.query.get_or_404(id)

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

        db.session.commit()

        return redirect(url_for("main.admin_apparence"))

    return render_template("admin/apparence.html", parametre=parametre)


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