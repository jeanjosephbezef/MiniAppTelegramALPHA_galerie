"""
Script de migration : ajoute la table `type_produit` (variétés nommées
comme Mimosa, GrapePie...) à la base existante, sans toucher aux
données déjà présentes.

Usage (depuis la racine du projet, avec le venv activé) :
    python migrate_types.py
"""

from app import create_app, db

app = create_app()

with app.app_context():

    inspecteur = db.inspect(db.engine)

    if "type_produit" in inspecteur.get_table_names():
        print("La table 'type_produit' existe déjà — rien à faire.")
    else:
        db.session.execute(db.text("""
            CREATE TABLE type_produit (
                id INTEGER PRIMARY KEY,
                produit_id INTEGER NOT NULL,
                nom VARCHAR(100) NOT NULL,
                ordre INTEGER DEFAULT 0,
                FOREIGN KEY(produit_id) REFERENCES produit(id)
            )
        """))
        db.session.commit()
        print("✅ Table 'type_produit' créée avec succès.")