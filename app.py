"""Local development entry point: `python app.py` (or VS Code's Run button).

The real server runs as a service instead; see deploy/README.md.
The code lives in the `creativity/` package."""
import os

from wsgi import app

if __name__ == "__main__":
    # Never enable debug on a public server: the debugger allows running code.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5555")), debug=os.getenv("FLASK_DEBUG") == "1")
