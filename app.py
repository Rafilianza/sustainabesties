"""A small local website for Victorian renters. Run with: python app.py."""

from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request

from calculations import REFERENCE, assess_home, validate_payload
from letters import create_letter

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
app.config["TEMPLATES_AUTO_RELOAD"] = True


@app.before_request
def keep_requests_local():
    # The local app must not become an API proxy for arbitrary websites.
    if request.host.split(":")[0] not in ["127.0.0.1", "localhost", "[::1]"]:
        return jsonify(error="Use the local preview address."), 403
    if request.method == "POST":
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            return jsonify(error="Use the assessment in the local website."), 403
        if not request.is_json:
            return jsonify(error="Send the assessment as JSON."), 415


@app.after_request
def response_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    )
    return response


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/methodology")
def methodology():
    return render_template("methodology.html", reference=REFERENCE)


@app.post("/api/assessment")
def assessment():
    payload = request.get_json(silent=True)
    home_details, errors = validate_payload(payload)
    if errors:
        return jsonify(errors=errors), 400
    result = assess_home(home_details, payload.get("selected_upgrades"), payload.get("disconnect_gas", False))
    return jsonify(result)


@app.post("/api/letter")
def letter():
    payload = request.get_json(silent=True)
    home_details, errors = validate_payload(payload)
    if errors:
        return jsonify(errors=errors), 400
    # Recalculate from validated answers; never trust totals sent by a browser.
    result = assess_home(home_details, payload.get("selected_upgrades"), payload.get("disconnect_gas", False))
    try:
        return jsonify(create_letter(result))
    except ValueError as error:
        return jsonify(error=str(error)), 400


@app.errorhandler(413)
def request_too_large(error):
    return jsonify(error="This request is too large. Use the assessment form."), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
