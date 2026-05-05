from flask import Flask
from flask_pymongo import PyMongo
from config import Config

# Initialize extensions
mongo = PyMongo()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions with app
    mongo.init_app(app)

    # Register blueprints
    from app.main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    # Context processors
    @app.context_processor
    def inject_admin_flags():
        from flask import session
        try:
            admin_exists = mongo.db.users.count_documents({'is_admin': True}) > 0
        except Exception:
            admin_exists = False
        return {
            'is_admin': session.get('is_admin', False),
            'admin_exists': admin_exists,
        }

    return app
