"""Production entry point: `gunicorn wsgi:app` (see deploy/creativity-feedback.service)."""
from creativity import create_app

app = create_app()
