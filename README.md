# DiscoverAI

A full-stack grocery e-commerce demo built to showcase two things together: a real shopping experience, and an agentic AI system (not a single API call) doing content moderation end-to-end — from PRD to intent spec to production code, with accuracy tracked over time.

## What It Is

DiscoverAI has two sides:

- **Storefront** — a customer-facing grocery shopping site with semantic (meaning-based, not just keyword) search, product browsing, cart, orders, and ratings/reviews.
- **Retailer Admin** — the operator side: review moderation, an AI moderation system that pre-screens reviews and explains its own reasoning, and an AI-generated review-summary tool.

A landing page lets a visitor choose either side (`Storefront` / `Retailer Admin`) without needing a real login — the project uses a small set of test personas instead of authentication.

## Key Use Cases

### Storefront
- Search products by meaning, not just exact keywords (OpenAI embeddings under the hood — e.g. searching "laptop for gaming" surfaces relevant results even without that literal phrase in the listing)
- Browse categories, view product detail pages
- Add to cart and place orders
- Read AI-generated review summaries on a product page (praises / criticism / neutral, in plain language)
- Submit a star rating + written review, with optional photos

### Retailer Admin
- **Review Moderation** — queue of submitted reviews, approve or reject with a reason code
- **AI Moderation** — run an on-demand, multi-agent AI check on submitted reviews (profanity, spam, personal info, irrelevance, hate speech, fraud/velocity, image policy), see the AI's recommended decision and reasoning, then accept it or override it; every AI-vs-human decision is logged so accuracy can be measured over time
- **Review Summary tool** — generate a 3-section AI summary (what customers praise, what they criticize, neutral observations) per product, edit it, and publish it to the live product page
- **Live "how it works" views** — for both AI Moderation and Review Summaries, a real-time popup shows the actual API calls happening step by step as you click the buttons — built for demos and for explaining "how did the AI arrive at this" to a non-technical audience

## Not Yet Built / Known Gaps

Being upfront about what this is (a portfolio demo) and isn't (production-ready):

- No real authentication — persona selection stands in for login
- No real payments — orders are simulated, nothing charges a card
- AI Moderation accuracy is measured (approve/reject agreement rate) but not yet fed back into tuning the agents' prompts
- No automated test suite yet

## Architecture

- **Frontend** — a single-file React app (no build step), Babel compiled in-browser, served by Flask from the same origin as the API
- **Backend** — Flask, one blueprint per feature area (reviews, moderation, search, review summaries, etc.)
- **Database** — PostgreSQL on Neon, using the `pgvector` extension for embeddings and `pg_trgm` for fuzzy text search
- **AI** — OpenAI `gpt-4o-mini` for the moderation agents and review summaries; `text-embedding-3-small` for semantic search
- **Real-time UI** — the browser's `BroadcastChannel` API drives the live "how it works" popups, so they reflect actual button clicks in another window rather than a scripted animation

**AI Moderation, specifically**, is 4 independent agents dispatched together rather than one do-everything prompt: text moderation (profanity/spam/relevance/personal info), hate speech (kept isolated so its prompt can be tuned without affecting the others), velocity/fraud (rule-based, no LLM — checks review-burst patterns and recent purchase history), and image policy (vision model, only runs if the review has photos). Their verdicts are combined with a fixed priority order, and a full trace of every agent's reasoning is stored per review for explainability.

## Getting Started

### Prerequisites
- Python 3.10+
- A Postgres database with the `pgvector` extension (Neon supports this out of the box)
- An OpenAI API key

### 1. Clone and set up the environment
```bash
git clone <your-repo-url>
cd discoverai
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment variables
Create a `.env` file at the repo root:
```
DATABASE_URL=postgresql://<user>:<password>@<host>/<dbname>?sslmode=require
OPENAI_API_KEY=sk-...
```

### 3. Set up the database schema
`schema.sql` at the repo root is a live snapshot of the full schema — pulled straight from the working database via `get_schema.py`, including the required extensions and sequences. Point it at your own empty Postgres/Neon database and run its contents (via `psql`, or paste into Neon's SQL Editor):
```bash
psql "$DATABASE_URL" -f schema.sql
```
To refresh `schema.sql` after a real schema change:
```bash
python get_schema.py
```
Read-only against the database — safe to run anytime.

### 4. Seed it with demo data
Two scripts round-trip the actual catalog, reviews, and moderation history as CSV, so a fresh setup isn't just empty tables:
```bash
python EXPORT_SEED_DATA.py    # run against a database that already has data
python LOAD_SEED_DATA.py      # dry run against the new database
python LOAD_SEED_DATA.py --apply
```
`EXPORT_SEED_DATA.py` is read-only against its source; `LOAD_SEED_DATA.py` only ever writes into empty tables and refuses to touch a table that already has rows.

### 5. Run it
```bash
cd backend
python app.py
```
Serves both API and frontend at `http://localhost:5050`.

## Design Docs

Two documents capture the product-thinking behind AI Moderation before any code was written:
- `AI_Moderation_PRD.docx` — the product requirements: problem, goals, proposed agents, open questions
- `AI_Moderation_Intent_Specification_v1.1.docx` — the locked technical spec: 4-agent architecture, aggregation logic, data contracts, velocity/fraud thresholds
