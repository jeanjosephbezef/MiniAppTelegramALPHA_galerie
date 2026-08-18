"""
Migration : ajoute la colonne 'taille_affichage' aux tables 'produit'
et 'category' si elle n'existe pas déjà.

Usage :
    python migrate_taille_affichage.py

Le script détecte le fichier de base SQLite automatiquement à partir
de la config Flask (SQLALCHEMY_DATABASE_URI). Si ça ne fonctionne pas
chez toi, modifie directement DB_PATH ci-dessous avec le chemin de
ton fichier .db (souvent dans instance/*.db).
"""

import sqlite3
import os
import sys

DB_PATH = None  # ex: "instance/boutique.db" -- laisse None pour auto-détection


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


def ajouter_colonne_si_absente(cursor, table):
    if colonne_existe(cursor, table, "taille_affichage"):
        print(f"✔ '{table}' a déjà la colonne taille_affichage, rien à faire.")
        return

    cursor.execute(
        f"ALTER TABLE {table} ADD COLUMN taille_affichage VARCHAR(20) DEFAULT 'moyenne'"
    )
    print(f"✔ Colonne taille_affichage ajoutée à '{table}'.")


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
        ajouter_colonne_si_absente(cursor, "produit")
        ajouter_colonne_si_absente(cursor, "category")

        # les lignes déjà existantes ont NULL par défaut malgré le DEFAULT SQL
        # (comportement SQLite sur ALTER TABLE) -> on les met à jour explicitement
        cursor.execute(
            "UPDATE produit SET taille_affichage = 'moyenne' WHERE taille_affichage IS NULL"
        )
        cursor.execute(
            "UPDATE category SET taille_affichage = 'moyenne' WHERE taille_affichage IS NULL"
        )

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