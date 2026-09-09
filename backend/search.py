"""
DiscoverAI Backend: Search Logic
=================================

This is the reusable "brain" behind the search feature, adapted from
SEMANTIC_SEARCH_TUTORIAL.py. It knows nothing about HTTP or Flask -
it just takes a query string and returns data. That separation means:

- It's easy to test on its own (call these functions directly)
- The same functions would work behind a mobile app's API calls too,
  not just this web frontend
"""

import os
import json

from openai import OpenAI
from dotenv import load_dotenv

from db import get_cursor

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
EMBEDDING_MODEL = 'text-embedding-3-small'

# Only these columns may be used for similarity search. embedding_type is
# spliced directly into the SQL string (Postgres can't parameterize column
# names), so this allow-list is what prevents SQL injection via that field.
ALLOWED_EMBEDDING_COLUMNS = {
    'embedding',
    'embedding_full',
    'embedding_category',
    'embedding_name',
}

DEFAULT_EMBEDDING_COLUMN = 'embedding_full'
MAX_LIMIT = 50
DEFAULT_LIMIT = 10

_client = None


def _get_client():
    """Create the OpenAI client on first use (lazy init)."""
    global _client
    if _client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Make sure .env exists and contains OPENAI_API_KEY."
            )
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


class SearchError(Exception):
    """Raised for expected, user-facing search problems (bad input, etc.)."""
    pass


def generate_query_embedding(query_text):
    """Convert a search query into a 1536-dimension embedding vector."""
    if not query_text or not query_text.strip():
        raise SearchError("Query cannot be empty.")

    client = _get_client()
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query_text.strip(),
    )
    return response.data[0].embedding


def search_products(query_text, limit=DEFAULT_LIMIT, embedding_type=DEFAULT_EMBEDDING_COLUMN):
    """
    Run a semantic search and return a list of matching products as
    plain dicts (JSON-serializable).

    Raises SearchError for bad input (caller should turn this into a 400).
    """
    # Validate inputs before touching the database
    if embedding_type not in ALLOWED_EMBEDDING_COLUMNS:
        raise SearchError(
            f"Invalid embedding_type '{embedding_type}'. "
            f"Must be one of: {', '.join(sorted(ALLOWED_EMBEDDING_COLUMNS))}"
        )

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise SearchError("limit must be an integer.")

    if limit < 1 or limit > MAX_LIMIT:
        raise SearchError(f"limit must be between 1 and {MAX_LIMIT}.")

    query_embedding = generate_query_embedding(query_text)
    embedding_str = json.dumps(query_embedding)

    # embedding_type is safe to splice in here because it was checked
    # against ALLOWED_EMBEDDING_COLUMNS above. limit is safe because it
    # was coerced to an int above (not a raw string from the request).
    # Also pulls description + attributes so we can reconstruct, for
    # explainability, the exact text that was embedded for this product.
    sql = f"""
        SELECT
            p.id,
            p.name,
            p.brand,
            p.price,
            p.description,
            c.path AS category,
            pa.pack_size,
            pa.quantity,
            pa.unit,
            pa.organic,
            pa.color,
            pa.size,
            pa.material,
            pa.storage_gb,
            pa.ram_gb,
            pa.processor,
            pa.attributes,
            p.image_url,
            p.in_stock,
            ROUND((1 - (p.{embedding_type} <=> %s::vector))::numeric * 100, 2) AS similarity,
            ROUND((p.{embedding_type} <=> %s::vector)::numeric, 6) AS distance
        FROM products p
        LEFT JOIN categories c ON p.category = c.id
        LEFT JOIN product_attributes pa ON p.id = pa.product_id
        WHERE p.{embedding_type} IS NOT NULL
        ORDER BY p.{embedding_type} <=> %s::vector
        LIMIT {limit};
    """

    with get_cursor() as cur:
        cur.execute(sql, (embedding_str, embedding_str, embedding_str))
        rows = cur.fetchall()

    results = []
    for rank, row in enumerate(rows, start=1):
        (product_id, name, brand, price, description, category,
         pack_size, quantity, unit, organic, color, size, material,
         storage_gb, ram_gb, processor, raw_attributes, image_url, in_stock,
         similarity, distance) = row

        # product_attributes.attributes is a free-form JSON blob whose
        # KEYS differ per category - fruits/veg store "prep_type"
        # (whole/peeled/sliced/...), rice and pulses store "variety" and
        # "polish", other categories may have none at all. psycopg2 has
        # returned this column as either an already-parsed dict or a raw
        # JSON string depending on driver version, so handle both rather
        # than assuming one.
        if isinstance(raw_attributes, dict):
            custom_attributes = raw_attributes
        elif raw_attributes:
            try:
                custom_attributes = json.loads(raw_attributes)
            except (TypeError, ValueError):
                custom_attributes = {}
        else:
            custom_attributes = {}

        embedded_text = _reconstruct_embedded_text(
            embedding_type=embedding_type,
            name=name,
            description=description,
            brand=brand,
            price=price,
            category_path=category,
            pack_size=pack_size,
            color=color,
            size=size,
            material=material,
            storage_gb=storage_gb,
            ram_gb=ram_gb,
            processor=processor,
        )

        results.append({
            "rank": rank,
            "id": product_id,
            "name": name,
            "brand": brand or "Generic",
            "price": float(price) if price is not None else None,
            "category": category,
            "pack_size": pack_size,
            "quantity": float(quantity) if quantity is not None else None,
            "unit": unit,
            "organic": bool(organic) if organic is not None else None,
            "custom_attributes": custom_attributes,
            "image_url": image_url,
            "in_stock": bool(in_stock) if in_stock is not None else True,
            "similarity": float(similarity) if similarity is not None else None,
            "distance": float(distance) if distance is not None else None,
            "embedded_text": embedded_text,
        })

    return results


def _reconstruct_embedded_text(embedding_type, name, description, brand, price,
                                category_path, pack_size, color, size, material,
                                storage_gb, ram_gb, processor):
    """
    Rebuild, as closely as possible, the exact text string that was fed to
    OpenAI when this product's embedding was generated (see
    FINAL_PRODUCTION_EMBEDDINGS_GENERATOR.py -> build_embedding_texts()).

    This is what powers the explainability feature - showing a user the
    literal text their query was compared against, not just the final score.
    """
    if embedding_type == 'embedding_name':
        return name or "Product"

    if embedding_type == 'embedding_category':
        return category_path or "Unknown"

    # embedding_full and the generic 'embedding' column both used the same
    # "full" text formula in the original generator script.
    full_text = f"{name} {description} {brand} {category_path} {price}"
    if pack_size:
        full_text += f" {pack_size}"
    if color:
        full_text += f" {color}"
    if size:
        full_text += f" {size}"
    if material:
        full_text += f" {material}"
    if storage_gb:
        full_text += f" {storage_gb}GB"
    if ram_gb:
        full_text += f" {ram_gb}GB RAM"
    if processor:
        full_text += f" {processor}"
    return full_text
