"""Login for the researcher-only pages."""
from functools import wraps

from flask import Response, g, request

from .storage import check_researcher_login, researcher_logins_exist


def researcher_only(view):
    """HTTP Basic auth (a login from .env or one added on /admin) for pages that
    expose participant data. Locked entirely if no password is configured."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not researcher_logins_exist():
            return Response("Set DASHBOARD_PASSWORD in the server's .env to enable this page.\n",
                            403, mimetype="text/plain")
        auth = request.authorization
        if not auth or not check_researcher_login(auth.username, auth.password):
            return Response("Password required.\n", 401, mimetype="text/plain",
                            headers={"WWW-Authenticate": 'Basic realm="Creativity study data"'})
        g.researcher = auth.username
        return view(*args, **kwargs)
    return wrapped
