"""The creativity-feedback study app. See CLAUDE.md for how the pieces fit."""
import logging
import threading

from flask import Flask
from flask_cors import CORS

from . import config


def create_app(preload_drawing_model=True):
    app = Flask(__name__,
                template_folder=f"{config.BASE_DIR}/templates",
                static_folder=f"{config.BASE_DIR}/static")
    # Drawings are sent as PNG data URLs; cap request size so nobody can fill the disk.
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
    CORS(app)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from .routes import participant, researcher
    app.register_blueprint(participant.bp)
    app.register_blueprint(researcher.bp)

    if preload_drawing_model:
        # Loading the drawing model takes several seconds; do it in the
        # background at startup so the first drawing isn't slow to score.
        from .scoring import get_ocsai
        threading.Thread(target=get_ocsai, name="preload-ocsai", daemon=True).start()
    return app
