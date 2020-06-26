import os
from flask import Flask, jsonify, request, url_for

app = Flask(__name__)


@app.route("/ping")
def ping():
    return jsonify(
        {
            "headers": dict(request.headers),
            "environ": dict(os.environ),
            "link": url_for("ping"),
            "external_link": url_for("ping", _external=True),
        }
    )


if __name__ == "__main__":
    app.run()
