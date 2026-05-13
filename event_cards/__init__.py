"""Event Cards package — Flask application factory."""

from flask import Flask

from . import config
from .routes.cards import cards_bp
from .routes.guests import guests_bp
from .routes.setup import setup_bp
from .routes.verify import verify_bp


def create_app():
    app = Flask(
        __name__,
        static_folder=str(config.STATIC_DIR),
        template_folder="templates",
    )
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB photo upload cap

    app.register_blueprint(guests_bp)
    app.register_blueprint(cards_bp)
    app.register_blueprint(verify_bp)
    app.register_blueprint(setup_bp)

    return app
