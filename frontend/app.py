import os
from flask import Flask, render_template

app = Flask(__name__)
API_BASE = os.environ.get("SWIFT_API_BASE", "http://localhost:8000")


def render_page(template, **context):
    return render_template(template, api_base=API_BASE, **context)


@app.get("/")
def overview():
    return render_page("overview.html")


@app.get("/queue")
def queue():
    return render_page("queue.html")


@app.get("/activity")
def activity():
    return render_page("activity.html")


@app.get("/system")
def system():
    return render_page("system.html")


@app.get("/swift/<path:reference>")
def detail(reference):
    return render_page("detail.html", reference=reference)


if __name__ == "__main__":
    app.run(port=5001, debug=True)
