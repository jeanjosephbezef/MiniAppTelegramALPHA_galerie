"""
Migration : ajoute à la table 'parametre' les colonnes manquantes pour
la page Admin > Apparence :
  - nom_boutique     (identité de la boutique)
  - logo             (identité de la boutique)
  - couleur_accent   (couleur d'accent)
  - message_bienvenue (texte envoyé par le bot au /start)

Sans danger à relancer plusieurs fois : chaque colonne n'est ajoutée
que si elle n'existe pas déjà, et les données déjà présentes ne sont
jamais touchées.

Usage (depuis la racine du projet, avec le venv activé) :
    python migrate_apparence.py
"""

import sqlite3
import os
import sys

DB_PATH = None  # ex: "instance/boutique.db" -- laisse None pour auto-détection

COLONNES_A_AJOUTER = {
    "nom_boutique": "VARCHAR(100)",
    "logo": "VARCHAR(255)",
    "couleur_accent": "VARCHAR(7)",
    "message_bienvenue": "VARCHAR(500)",
}


def trouver_chemin_db():
    if DB_PATH:
        return DB_PATH

    # tentative d'auto-détection via la config de l'app Flask
    try:
        sys.path.insert(0, os.getcwd())
        from app import create_app  # adapte si ta factory a un autre nom/chemin
        app = create_app()
        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        if uri.startswith("sqlite:///"):
            chemin = uri.replace("sqlite:///", "", 1)
            if not os.path.isabs(chemin):
                chemin = os.path.join(app.instance_path, os.path.basename(chemin)) \
                    if not os.path.exists(chemin) else chemin
            return chemin
    except Exception as e:
        print(f"Auto-détection impossible ({e}).")

    return None


def colonne_existe(cursor, table, colonne):
    cursor.execute(f"PRAGMA table_info({table})")
    colonnes = [row[1] for row in cursor.fetchall()]
    return colonne in colonnes


def ajouter_colonnes_manquantes(cursor, table):
    for colonne, type_sql in COLONNES_A_AJOUTER.items():
        if colonne_existe(cursor, table, colonne):
            print(f"✔ '{table}' a déjà la colonne {colonne}, rien à faire.")
            continue

        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {colonne} {type_sql}")
        print(f"✔ Colonne {colonne} ajoutée à '{table}'.")


def main():
    chemin = trouver_chemin_db()

    if not chemin:
        chemin = input("Chemin du fichier .db (ex: instance/boutique.db) : ").strip()

    if not os.path.exists(chemin):
        print(f"✗ Fichier introuvable : {chemin}")
        sys.exit(1)

    print(f"Base utilisée : {chemin}")

    conn = sqlite3.connect(chemin)
    cursor = conn.cursor()

    try:
        ajouter_colonnes_manquantes(cursor, "parametre")

        conn.commit()
        print("Migration terminée avec succès.")
    except sqlite3.Error as e:
        conn.rollback()
        print(f"✗ Erreur pendant la migration : {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
