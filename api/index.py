"""Vercel serverless entry point for Papier Lab Flask app."""
import sys
import os

# Ensure the project root is on sys.path so `app` is importable on Vercel.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
