import os
from flask import Flask, session
from flask_migrate import Migrate
from dotenv import load_dotenv
from db import db            # import de l'instance unique
from models import bcrypt
from routes import main_bp
import secrets

load_dotenv()

def create_app():
    app = Flask(__name__,template_folder='templates', static_folder='static')
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    bcrypt.init_app(app)

    migrate = Migrate(app, db)

    @app.context_processor
    def inject_csrf_token():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(16)
        return dict(csrf_token=lambda: session['csrf_token'])

    app.register_blueprint(main_bp)

    return app

    app = create_app()
if __name__ == "__main__":
    app.run(debug=True)