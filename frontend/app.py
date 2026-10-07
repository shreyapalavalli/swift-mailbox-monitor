import os

from flask import Flask, render_template

app = Flask(__name__)
API_BASE = os.environ.get("SWIFT_API_BASE", "http://localhost:8000")


@app.context_processor
def inject_api():
    return {"api_base": API_BASE}


@app.get("/")
def overview():
    return render_template("overview.html")


@app.get("/queue")
def queue():
    return render_template("queue.html")


@app.get("/swift/<path:reference>")
def detail(reference):
    return render_template("detail.html", reference=reference)


@app.get("/activity")
def activity():
    return render_template("activity.html")


@app.get("/system")
def system():
    return render_template("system.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
