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

    sous_categories = db.relationship(
        "Category",
        backref="categorie_principale",
        order_by="Category.nom"
    )


class Category(db.Model):
    """Sous-catégorie, rattachée (optionnellement) à une catégorie
    principale. C'est ce que Produit.categorie référence par son nom."""

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    image = db.Column(db.String(255), default="default.jpg")
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