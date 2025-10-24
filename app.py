from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("main.html")

if __name__ == "__main__":
    # Run on port 5555, accessible from localhost
    app.run(host="0.0.0.0", port=5555, debug=True)
