from run import app
from app import db
from app.models import Produit


with app.app_context():

    produits = [

        Produit(
            nom="Fleur CBD Premium",
            description="Fleur CBD sélection premium",
            prix=25.00,
            stock=50,
            image="fleur.jpg",
            categorie="Fleurs",
            cbd="10%",
            thc="<0.3%",
            origine="France"
        ),

        Produit(
            nom="Résine CBD Gold",
            description="Résine CBD qualité supérieure",
            prix=30.00,
            stock=30,
            image="resine.jpg",
            categorie="Résines",
            cbd="25%",
            thc="<0.3%",
            origine="Europe"
        ),

        Produit(
            nom="Huile CBD 10%",
            description="Huile CBD bien-être",
            prix=40.00,
            stock=20,
            image="huile.jpg",
            categorie="Huiles",
            cbd="10%",
            thc="<0.3%",
            origine="France"
        )

    ]


    db.session.add_all(produits)

    db.session.commit()


    print("✅ Produits ajoutés")