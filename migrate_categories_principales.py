"""
Script de migration : ajoute la table `categorie_principale` et la
colonne `categorie_principale_id` sur `category`, sans toucher aux
données déjà présentes.

Usage (depuis la racine du projet, avec le venv activé) :
    python migrate_categories_principales.py
"""

from app import create_app, db

app = create_app()

with app.app_context():

    inspecteur = db.inspect(db.engine)

    if "categorie_principale" in inspecteur.get_table_names():
        print("La table 'categorie_principale' existe déjà — rien à faire pour la table.")
    else:
        db.session.execute(db.text("""
            CREATE TABLE categorie_principale (
                id INTEGER PRIMARY KEY,
                nom VARCHAR(100) NOT NULL,
                image VARCHAR(255) DEFAULT 'default.jpg'
            )
        """))
        db.session.commit()
        print("✅ Table 'categorie_principale' créée avec succès.")

    colonnes_category = [c["name"] for c in inspecteur.get_columns("category")]

    if "categorie_principale_id" in colonnes_category:
        print("La colonne 'categorie_principale_id' existe déjà sur 'category' — rien à faire.")
    else:
        db.session.execute(db.text(
            "ALTER TABLE category ADD COLUMN categorie_principale_id INTEGER "
            "REFERENCES categorie_principale(id)"
        ))
        db.session.commit()
        print("✅ Colonne 'categorie_principale_id' ajoutée à 'category'.")