# Le Filon 74 — Mini App Telegram

Boutique en ligne (mini-application Telegram) avec back-office admin, construite avec **Flask** (backend + boutique) et **python-telegram-bot** (bot Telegram).

## Stack technique

- **Backend** : Flask + SQLAlchemy (SQLite)
- **Bot Telegram** : python-telegram-bot
- **Frontend** : templates Jinja2, CSS custom (thème sombre / accents verts côté boutique, thème "botanique" clair côté admin)
- **Tunnel de dev** : ngrok

## Structure du projet

```
MiniAppTelegramALPHA/
├── app/
│   ├── routes.py          # toutes les routes Flask (boutique + admin)
│   ├── models.py          # modèles SQLAlchemy (Produit, Variante, MediaProduit, Category, Commande, ZoneLivraison, Parametre)
│   ├── security.py        # vérification Telegram initData, logs, alertes, blocage d'IDs
│   ├── static/
│   │   ├── css/
│   │   │   ├── style.css      # styles boutique (client)
│   │   │   └── admin.css      # styles espace admin
│   │   ├── images/
│   │   └── videos/
│   └── templates/
│       ├── base.html          # gabarit commun (header/footer boutique, dock catégories, fond d'écran)
│       ├── accueil.html       # page d'accueil (hero centré, sans nav)
│       ├── produit.html       # fiche produit client (image/vidéo + galerie + variantes)
│       ├── produits.html      # liste des produits
│       ├── panier.html
│       ├── checkout.html
│       └── admin/
│           ├── base_admin.html    # gabarit admin (sidebar + contenu)
│           ├── login.html         # connexion admin (mot de passe web)
│           ├── dashboard.html     # tableau de bord (stats + dernières commandes)
│           ├── commandes.html     # liste complète des commandes (contact client cliquable)
│           ├── produits.html      # liste produits (admin)
│           ├── produit_form.html  # création produit (image/vidéo effaçables avant envoi)
│           ├── modifier_produit.html   # modification produit (+ galerie, suppression image/vidéo)
│           ├── categories.html    # liste catégories (miniatures)
│           ├── categorie_form.html     # création catégorie (image effaçable avant envoi)
│           ├── modifier_categorie.html # modification catégorie (+ suppression image)
│           ├── livraison.html     # configuration des frais de livraison par ville
│           ├── zone_form.html
│           └── apparence.html     # fond d'écran + dock de catégories
├── database/
│   └── app.db              # base SQLite
├── security.log             # journal de toutes les tentatives d'accès admin (créé automatiquement)
├── blocked_ids.json          # IDs Telegram bloqués manuellement (créé automatiquement si besoin)
├── bot.py                   # bot Telegram (reconnaissance admin, boutons, /commandes)
├── run.py                   # lancement du serveur Flask
├── requirements.txt
└── .env                      # variables d'environnement (non versionné)
```

## Lancer le projet en local

```bash
# backend Flask
python run.py

# bot Telegram (dans un autre terminal)
python bot.py

# tunnel pour exposer le backend à Telegram
ngrok http 5000
```

Après chaque redémarrage de ngrok, mettre à jour `WEBAPP_URL` dans `.env` avec la nouvelle URL générée, puis redémarrer `bot.py`.

## Variables d'environnement (`.env`)

| Variable              | Description                                                              |
|-----------------------|---------------------------------------------------------------------------|
| `BOT_TOKEN`            | Token du bot Telegram (BotFather)                                         |
| `WEBAPP_URL`           | URL publique (ngrok) pointant vers le serveur Flask                       |
| `ADMIN_PASSWORD`       | Mot de passe de la page web `/admin/login`                                |
| `BOT_ADMIN_PASSWORD`   | Mot de passe demandé dans le bot Telegram (séparé du précédent)           |
| `ADMIN_TELEGRAM_IDS`   | IDs Telegram admin, séparés par des virgules (ex: `8702997904,0000000000`) — lus à la fois par `bot.py` et `app/security.py`, une seule liste à tenir à jour |

## Authentification & sécurité admin

Deux façons d'accéder à l'espace admin, plus une couche de surveillance commune :

1. **Dans le bot Telegram** : `/start` reconnaît automatiquement les ID Telegram listés dans `ADMIN_TELEGRAM_IDS`, puis demande `BOT_ADMIN_PASSWORD`. Le message contenant le mot de passe est supprimé automatiquement du chat après lecture. `/admin` et `/commandes` ne répondent que si l'ID est reconnu (silence total sinon). `/logout` nettoie l'historique de la session en cours.
2. **Sur la page web** (`/admin/login`) : demande `ADMIN_PASSWORD`.
3. **Vérification Telegram native** (`/admin/verify-telegram`) : `app/security.py` vérifie la signature cryptographique des données Telegram WebApp (`initData`) pour confirmer qu'une requête vient bien d'un utilisateur Telegram authentique et autorisé.

**Toute tentative échouée** (mauvais mot de passe web, mauvais mot de passe bot, `/admin`/`/commandes` par un ID non autorisé, `initData` invalide) est :
- **journalisée** dans `security.log` (JSON par ligne : date, ID, username, IP, géolocalisation approximative, navigateur, autorisé ou non) ;
- **notifiée immédiatement par Telegram** à tous les IDs listés dans `ADMIN_TELEGRAM_IDS`, avec le détail complet de la tentative.

Un ID Telegram peut être bloqué manuellement en l'ajoutant à `blocked_ids.json` (lu par `security.charger_ids_bloques`).

Le bouton menu Telegram et la mini-app en lien direct (BotFather) ont été retirés : `/start` est le seul point d'entrée public du bot.

## Gestion des produits et catégories

- Le **prix** n'est plus saisi directement : il est calculé automatiquement comme le prix de la **variante la moins chère** (poids/prix). Au moins une variante est nécessaire pour qu'un produit soit commandable.
- Le **stock** n'est plus géré depuis l'admin (suivi manuel en dehors du site) ; le champ reste en base à `0` par défaut et n'est plus affiché aux clients.
- **CBD / THC** sont optionnels : une case à cocher active le champ, avec le choix de préciser un taux exact ou juste indiquer la présence ("Oui").
- **Image et vidéo principales** : peuvent être **remplacées** (nouvel upload) ou **supprimées** (case à cocher dédiée sur la page de modification — repasse à l'image par défaut / retire la vidéo, et supprime aussi le fichier du disque). Sur les formulaires de **création**, un bouton "✕ Retirer" permet d'annuler la sélection d'un fichier avant même d'envoyer le formulaire.
- **Galerie** (`MediaProduit`) : photos et vidéos supplémentaires ajoutables librement à un produit, affichées en miniatures sur la fiche produit ; chaque média peut être retiré individuellement (fichier supprimé du disque en plus de la ligne en base).
- **Miniatures** : les listes admin (produits, catégories) affichent une vignette (`.admin-thumb`, 56×56px) plutôt que l'image en taille réelle.

## Commandes

- **Panier / checkout** : choix meet up ou livraison, ville en saisie libre (aucun frais appliqué si la ville ne correspond à aucune zone configurée).
- **Admin → Commandes** : liste complète (pas seulement les dernières), avec articles commandés, mode, adresse/ville/frais, statut, et un **lien direct vers la conversation Telegram du client** (construit depuis ce qu'il a saisi au checkout : `@pseudo` ou ID numérique).
- Actions rapides : marquer **Terminée** ou **Annulée**, ou vider tout l'historique.
- Depuis le bot : `/commandes` (admin uniquement) liste les commandes en attente et permet de **corriger la ville** directement dans le chat si le client ne l'a pas renseignée (recalcule automatiquement les frais et le total).

## Livraison

Frais configurables **par ville** (`ZoneLivraison.ville` → prix) et minimum de commande requis pour la livraison (`Parametre.minimum_livraison`), gérés depuis l'espace admin. La comparaison de ville est insensible à la casse.

## Apparence

Depuis `/admin/apparence` : changer le fond d'écran de toute l'application (ou réinitialiser au défaut), et activer/désactiver le dock de catégories affiché en bas de la boutique.

## Notes

- Base de données modifiée manuellement via `sqlite3 ./database/app.db` (pas de Flask-Migrate sur ce projet) — toute évolution du modèle nécessite un `ALTER TABLE` manuel.
- `security.log` et `blocked_ids.json` sont créés automatiquement à la racine du projet au premier besoin — à ne jamais versionner (données sensibles).