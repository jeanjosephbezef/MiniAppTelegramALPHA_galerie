from app import create_app, db
from app.models import Category, Produit


app = create_app()


with app.app_context():

    Produit.query.delete()
    Category.query.delete()


    electronique = Category(
        nom="Électronique",
        image="electronique.png"
    )

    mode = Category(
        nom="Mode",
        image="mode.png"
    )

    accessoires = Category(
        nom="Accessoires",
        image="accessoires.png"
    )


    db.session.add_all([
        electronique,
        mode,
        accessoires
    ])

    db.session.commit()



    produits = [

        Produit(
            nom="Casque Bluetooth",
            description="Casque sans fil haute qualité",
            prix=49.99,
            stock=10,
            image="casque.jpg",
            categorie_id=electronique.id
        ),

        Produit(
            nom="Montre connectée",
            description="Montre intelligente",
            prix=79.99,
            stock=5,
            image="montre.jpg",
            categorie_id=electronique.id
        ),

        Produit(
            nom="Sweat Premium",
            description="Sweat confortable",
            prix=39.99,
            stock=20,
            image="sweat.jpg",
            categorie_id=mode.id
        ),

        Produit(
            nom="Sac à dos",
            description="Sac pratique",
            prix=29.99,
            stock=15,
            image="sac.jpg",
            categorie_id=accessoires.id
        )

    ]


    db.session.add_all(produits)

    db.session.commit()


    print("Produits ajoutés avec succès ✅")