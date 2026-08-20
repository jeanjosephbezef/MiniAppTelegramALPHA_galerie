"""
Migration : ajoute
  - la colonne 'actif' (booléen) à la table 'produit'
  - la colonne 'ordre' (entier) aux tables 'category' et
    'categorie_principale'
sans toucher aux données déjà présentes.

Usage (depuis la racine du projet, avec le venv activé) :
    python migrate_actif_ordre.py

Le script détecte le fichier de base SQLite automatiquement à partir
de la config Flask (SQLALCHEMY_DATABASE_URI). Si ça ne fonctionne pas
chez toi, renseigne DB_PATH directement (souvent dans instance/*.db).
"""

import sqlite3
import os
import sys

DB_PATH = None  # ex: "instance/boutique.db" -- laisse None pour auto-détection


def trouver_chemin_db():
    if DB_PATH:
        return DB_PATH

    try:
        sys.path.insert(0, os.getcwd())
        from app import create_app
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
        if colonne_existe(cursor, "produit", "actif"):
            print("✔ 'produit.actif' existe déjà, rien à faire.")
        else:
            cursor.execute("ALTER TABLE produit ADD COLUMN actif BOOLEAN DEFAULT 1")
            cursor.execute("UPDATE produit SET actif = 1 WHERE actif IS NULL")
            print("✔ Colonne 'actif' ajoutée à 'produit' (tous les produits existants restent actifs).")

        for table in ("category", "categorie_principale"):
            if colonne_existe(cursor, table, "ordre"):
                print(f"✔ '{table}.ordre' existe déjà, rien à faire.")
            else:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN ordre INTEGER DEFAULT 0")
                cursor.execute(f"UPDATE {table} SET ordre = 0 WHERE ordre IS NULL")
                print(f"✔ Colonne 'ordre' ajoutée à '{table}'.")

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
