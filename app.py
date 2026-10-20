from flask import Flask, render_template, request, jsonify
import json
import os
from pathlib import Path

app = Flask(__name__)

SCORES_FILE = Path("snake_highscores.json")


def load_scores():
    try:
        with SCORES_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/scores", methods=["GET"])
def get_scores():
    return jsonify(load_scores())


@app.route("/scores", methods=["POST"])
def save_score():
    data = request.get_json(silent=True) or {}

    try:
        score = int(data.get("score", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid score"}), 400

    if score < 0 or score > 1000000:
        return jsonify({"error": "Score out of range"}), 400

    scores = load_scores()
    scores.append({"score": score})
    scores = sorted(
        scores, key=lambda item: int(item.get("score", 0)), reverse=True
    )[:10]

    try:
        with SCORES_FILE.open("w", encoding="utf-8") as file:
            json.dump(scores, file, indent=2)
    except OSError:
        return jsonify({"error": "Could not save score"}), 500

    return jsonify(scores)


if __name__ == "__main__":
    app.run(debug=True)
