from datetime import datetime

from . import db


# ==========================
# PRODUITS
# ==========================

class Produit(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    prix = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    image = db.Column(db.String(255), default="default.jpg")
    video = db.Column(db.String(255))
    categorie = db.Column(db.String(100))
    cbd = db.Column(db.String(50))
    thc = db.Column(db.String(50))
    origine = db.Column(db.String(100))
    actif = db.Column(db.Boolean, default=True, nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    variantes = db.relationship(
        "Variante",
        backref="produit",
        cascade="all, delete-orphan",
        order_by="Variante.prix"
    )

    types = db.relationship(
        "TypeProduit",
        backref="produit",
        cascade="all, delete-orphan",
        order_by="TypeProduit.ordre"
    )

    medias = db.relationship(
        "MediaProduit",
        backref="produit",
        cascade="all, delete-orphan",
        order_by="MediaProduit.ordre"
    )


# ==========================
# VARIANTES (poids / prix)
# ==========================

class Variante(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    produit_id = db.Column(
        db.Integer, db.ForeignKey("produit.id"), nullable=False
    )
    poids = db.Column(db.String(50), nullable=False)   # ex: "2g", "10g"
    prix = db.Column(db.Float, nullable=False)          # ex: 50.0, 350.0


# ==========================
# MEDIAS SUPPLEMENTAIRES (galerie photos / vidéos d'un produit)
# ==========================

class MediaProduit(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    produit_id = db.Column(
        db.Integer, db.ForeignKey("produit.id"), nullable=False
    )
    fichier = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(10), nullable=False)   # "image" ou "video"
    ordre = db.Column(db.Integer, default=0)


# ==========================
# TYPES / VARIÉTÉS NOMMÉES (ex: Mimosa, GrapePie...)
# ==========================

class TypeProduit(db.Model):
    """Variétés/déclinaisons nommées d'un produit (indépendantes du
    poids) — ex: Mimosa, GrapePie, Zkittlez. Le client choisit un type
    en plus du poids ; le prix reste géré par les variantes de poids."""

    id = db.Column(db.Integer, primary_key=True)
    produit_id = db.Column(
        db.Integer, db.ForeignKey("produit.id"), nullable=False
    )
    nom = db.Column(db.String(100), nullable=False)
    ordre = db.Column(db.Integer, default=0)


# ==========================
# CATEGORIES
# ==========================

class CategoriePrincipale(db.Model):
    """Catégorie de premier niveau (ex: Fleurs, Hash, Extract).
    Regroupe plusieurs sous-catégories (Category)."""

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    image = db.Column(db.String(255), default="default.jpg")
    ordre = db.Column(db.Integer, default=0)

    sous_categories = db.relationship(
        "Category",
        backref="categorie_principale",
        order_by="Category.ordre, Category.nom"
    )


class Category(db.Model):
    """Sous-catégorie, rattachée (optionnellement) à une catégorie
    principale. C'est ce que Produit.categorie référence par son nom."""

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    image = db.Column(db.String(255), default="default.jpg")
    ordre = db.Column(db.Integer, default=0)
    categorie_principale_id = db.Column(
        db.Integer, db.ForeignKey("categorie_principale.id"), nullable=True
    )


# ==========================
# COMMANDES
# ==========================

class Commande(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    client = db.Column(db.String(100))
    telegram_id = db.Column(db.String(100))
    produits = db.Column(db.Text)
    total = db.Column(db.Float)
    mode_retrait = db.Column(db.String(20))
    adresse = db.Column(db.String(255))
    ville = db.Column(db.String(100))
    frais_livraison = db.Column(db.Float, default=0)
    statut = db.Column(db.String(50), default="En attente")
    date = db.Column(db.DateTime, default=datetime.utcnow)


# ==========================
# ZONES LIVRAISON (par ville)
# ==========================

class ZoneLivraison(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    ville = db.Column(db.String(100), nullable=False, unique=True)
    prix = db.Column(db.Float, nullable=False)


# ==========================
# PARAMETRES BOUTIQUE
# ==========================

class Parametre(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    minimum_livraison = db.Column(db.Float, default=150)

    # Nom du fichier (dans static/images) utilisé comme fond d'écran de
    # toute l'appli. Si vide, on retombe sur le fond par défaut du CSS.
    fond_ecran = db.Column(db.String(255))

    # Active ou non le dock de catégories affiché en bas de l'appli.
    dock_categories_actif = db.Column(db.Boolean, default=True)

    # Texte défilant affiché en bandeau d'annonce en haut de l'accueil.
    # Vide -> aucun bandeau affiché.
    annonce_texte = db.Column(db.String(255))

    # --- Identité visuelle, pilotable depuis Admin > Apparence ---

    # Nom affiché dans le titre de l'onglet et le pied de page.
    # Vide -> on retombe sur "Le Filon 74" par défaut.
    nom_boutique = db.Column(db.String(100))

    # Nom du fichier (dans static/images) utilisé comme logo. Vide -> pas de logo.
    logo = db.Column(db.String(255))

    # Couleur d'accent (format hexadécimal, ex: "#4fc3f7") utilisée pour les
    # boutons, liens et surlignages sur toute l'appli (boutique + admin).
    # Vide -> couleur bleu glace par défaut définie dans le CSS.
    couleur_accent = db.Column(db.String(7))

    # Message envoyé par le bot Telegram quand un client fait /start.
    # Vide -> on retombe sur le message par défaut codé dans bot.py.
    message_bienvenue = db.Column(db.String(500))

    # --- Bannière promo / annonce colorée en haut de l'accueil ---
    promo_banniere_active = db.Column(db.Boolean, default=False)
    promo_banniere_texte = db.Column(db.String(200))
    promo_banniere_couleur = db.Column(db.String(7), default="#ff4444")

    # --- Badges produits ---
    badge_nouveau_actif = db.Column(db.Boolean, default=False)
    badge_nouveau_jours = db.Column(db.Integer, default=7)
    badge_promo_actif = db.Column(db.Boolean, default=False)

    # --- Devise ---
    devise_symbole = db.Column(db.String(10), default="€")
    devise_position = db.Column(db.String(10), default="apres")  # "avant" ou "apres"

    # --- Pied de page / contact ---
    footer_actif = db.Column(db.Boolean, default=True)
    footer_texte = db.Column(db.String(200))
    contact_telegram = db.Column(db.String(100))

    # --- Réseaux sociaux ---
    social_instagram = db.Column(db.String(150))
    social_telegram_channel = db.Column(db.String(150))

    # --- Mode maintenance ---
    maintenance_active = db.Column(db.Boolean, default=False)
    maintenance_message = db.Column(
        db.String(200), default="Boutique en maintenance, revenez bientôt !"
    )

    # --- CSS personnalisé (avancé) ---
    css_personnalise = db.Column(db.Text)

    # --- Thème & couleurs ---
    theme_mode = db.Column(db.String(10), default="dark")       # "dark" ou "light"
    background_color = db.Column(db.String(7))                   # fond uni si pas de fond_ecran
    couleur_secondaire = db.Column(db.String(7))                 # cartes / sections
    couleur_texte = db.Column(db.String(7))

    # --- Typographie ---
    police = db.Column(db.String(50), default="Inter")           # Inter, sans-serif, serif, monospace, Poppins
    taille_texte_base = db.Column(db.Integer, default=16)        # px

    # --- Identité (compléments) ---
    slogan = db.Column(db.String(150))
    banniere = db.Column(db.String(255))                         # image large en haut de l'accueil

    # --- Dock catégories (style + ordre géré via Category.ordre) ---
    dock_style = db.Column(db.String(10), default="both")        # "icones", "texte", "both"

    # --- Cartes produits ---
    style_carte = db.Column(db.String(10), default="rounded")    # "rounded", "square", "minimal"
    arrondi_carte = db.Column(db.Integer, default=15)            # px
    produits_par_ligne = db.Column(db.Integer, default=0)        # 0 = auto, sinon 1/2/3
    badge_stock_actif = db.Column(db.Boolean, default=False)

    # --- Boutons & effets ---
    style_bouton = db.Column(db.String(10), default="filled")    # "filled", "outline", "ghost"
    animations_actives = db.Column(db.Boolean, default=True)

    # --- Écran de chargement (splash) à l'ouverture de la mini app ---
    splash_actif = db.Column(db.Boolean, default=False)
    splash_logo = db.Column(db.String(255))                      # image affichée pendant le chargement
    splash_texte = db.Column(db.String(100))                     # texte optionnel sous le logo
    splash_couleur_fond = db.Column(db.String(7), default="#0d0d0d")
    splash_duree = db.Column(db.Integer, default=1500)           # ms