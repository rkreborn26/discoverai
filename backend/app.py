"""
DiscoverAI: Flask Application Entry Point
===========================================

Serves both the API and the frontend from a single app/origin. This is
deliberate: it means there's no CORS configuration needed locally, and
deploying later is just "run this same app on a host" - nothing to
restructure between local development and production.

Run locally:
    cd backend
    python app.py

Then open http://localhost:5000 in a browser.
"""

from flask import Flask, send_from_directory

from routes.search_routes import api
from routes.discovery_routes import discovery
from routes.autosuggest_routes import autosuggest
from routes.cart_routes import cart
from routes.reviews_routes import reviews
from routes.review_summary_routes import review_summary
from routes.moderation_routes import moderation

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.register_blueprint(api)
app.register_blueprint(discovery)
app.register_blueprint(autosuggest)
app.register_blueprint(cart)
app.register_blueprint(reviews)
app.register_blueprint(review_summary)
app.register_blueprint(moderation)


@app.route('/')
def index():
    """Serve the frontend's single HTML file."""
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/<path:client_route>')
def client_side_route(client_route):
    """
    The frontend uses client-side routing (React Router) for /search and
    /results - Flask itself only knows about one real page. Without this,
    refreshing the browser on /search or /results (or sharing that URL)
    would 404 at the Flask level. This serves the same index.html for any
    non-API, non-static path and lets React Router take it from there.
    """
    return send_from_directory(app.static_folder, 'index.html')


if __name__ == '__main__':
    # Port 5000 was already taken by another local project (BD Ordering Portal),
    # so DiscoverAI runs on 5050 instead to avoid any conflict.
    app.run(debug=True, host='0.0.0.0', port=5050)
