# Auto Suggestion — AI Product Management Plan

Source: `requirements/Roadmap.xlsx`, tab **Auto Suggestion**. Working doc, filled in as we go through each step together.

## Roadmap source material

| Search Journey | Problem Hypothesis | Solution |
|---|---|---|
| Popular Searches | Customers' top searches don't change much for grocery shopping — these are searches popular on ecommerce apps generally; for our case we assume globally popular searches. | Show popular searches on the search initiation page (the page that opens when the customer clicks the search box). |
| Auto Suggestion | Customers find it tough to frame a whole query. We want to give them query-completion suggestions based on prefix matches with popular past queries, and queries matching leaf category names, etc. | *(not yet defined)* |
| Auto Suggestion — Anchored in category, brand, other attributes | Customers often need a forward direction while typing a query. | e.g. typing "milk" surfaces "Milk Nandhini," "Organic Milk," "A2 Milk," "Milk Packet 1kg"; typing "rice" surfaces "Basmati Rice," "Dawat Basmati Rice," "Idli Rice." Suggestions generally take the shape `<category>, <brand>, <type>, <attributes>` and are shown as the customer types. |

---

## Step 1 — AI Product Discovery

**Reframing the roadmap.** The three roadmap rows aren't three features — they're two UX moments. "Popular Searches" is the *zero-query state* (search box tapped, nothing typed). "Auto Suggestion" and "Auto Suggestion — Anchored" are the same *as-you-type* moment; the anchored version isn't a separate feature, it's the good version of plain prefix-matching (matching on `<category>, <brand>, <type>, <attributes>` instead of raw query strings only). Plain Auto Suggestion is treated as a naive fallback, not a separate deliverable.

**Reality check.** DiscoverAI has no real user traffic or query logs — it's a demo catalog, not a live store. "Assume globally popular searches" (per the roadmap hypothesis) has to mean *seeded* defaults today, with a path to real dynamic popularity once real usage exists.

**Catalog-coverage gap found during discovery.** Checked the 23 candidate seed queries against what's actually in the DB. 6 have zero/near-zero product coverage because their categories don't exist yet: **milk** (Dairy), **chocolates** (Confectionery), **coffee** / **tea** (Beverages), **chilli powder** / **coriander powder** (packaged Spices & Masalas — fresh coriander leaves and green chilli exist as vegetables, but not the ground/packaged spice). Shipping these as popular-search suggestions would mean a customer's first interaction with the feature is a tap that leads to an empty results page — directly undermines the feature's purpose.
- **Decision:** ship with the 17 queries that have real coverage. Park the other 6 to be added once Dairy, Beverages, Confectionery, and Spices & Masalas categories are built.

## Step 2 — AI-Led Scoping

**In scope for this iteration:**
- Popular Searches (zero-query state) only. Full Auto Suggestion (as-you-type completion) is explicitly deferred — same discovery → scoping → solutioning framework will be re-run for it later.
- A new **Home page** (dummy/visual for now) as the app's entry point — the app currently has none; it opens straight into search.
- A dedicated **Search page** (opens on search-box tap) showing Popular Searches.
- The existing Results page (SERP), unchanged.

**Seed set:** 17 queries — ghee, dal, oil, cooking oil, vegetables, oranges, mangoes, atta, moong, tata sampann dal, potato, onion, spinach, blueberries, watermelon, bananas, apples. Shown in randomized order per page load for cold-start variety.

**Popularity algorithm (designed now, real data plumbing deferred — see gap below):**
- Metrics per query, over a **rolling 7-day window**: search volume (count of times the query string was searched), click-through rate (product clicks on that query's results ÷ volume), add-to-cart rate (add-to-cart events on that query's results ÷ volume).
- Volume is **log-scaled** before normalization, so one dominant query (e.g. "milk") doesn't crush every other query's normalized score toward 0.
- Each of the 3 metrics is **min-max normalized** to 0–1: `(value_i − min) / (max − min)`.
- **Weighting:** 1/3 volume + 1/3 CTR + 1/3 cart-rate = popularity score.
- **Replacement rule:** default seed queries only get displaced by a real customer-typed query once that query's volume reaches **≥30** in the rolling window — protects against small-sample noise overriding the curated defaults.

**Known dependency — no events tracking exists yet.** There's no logging today for searches, result clicks, or add-to-cart actions anywhere in the schema. The dynamic scoring algorithm above cannot run until that's built. **DiscoverAI also has no add-to-cart feature at all** — it's a search-only demo — so the cart-rate leg of the formula has no data source until at minimum a stub "Add to Cart" action exists somewhere in the UI. Today's build ships the static 17-query seed list only; dynamic scoring is a documented follow-up, not part of this iteration.

## Step 3 — AI-Led Framing / Solutioning

### UX flow (working backwards)

1. **Home** (dummy/visual) — mobile-first, tile grid of the **29 actual leaf categories** (product-bearing, not the ~6 abstract parent groupings) under **Fruits / Vegetables / Staples** section headings. Search bar pinned at top. A banner strip below the search bar: "Fresh selection, delivered to you in 15 minutes."
2. Tap the search bar → **Search page** opens, showing the 17 seeded Popular Searches, shuffled, as tappable chips.
3. Tap a chip → **jumps straight to Results** (no intermediate fill-and-confirm step) — one tap, done.

### Navigation architecture

**Client-side routing via React Router** (CDN build — no bundler/build step needed, consistent with the existing React-via-CDN setup). Real distinct URLs (`/`, `/search`, `/results`) with working back button and bookmarkable links, but instant view-swapping instead of full page reloads — chosen because a reload on every chip tap would undercut the "one tap, done" interaction the whole feature is designed around.

### Open items before development starts
- `categories.icon_url` is unpopulated for every category — the Home page tile grid needs either real icons or an agreed placeholder scheme (emoji / initials / solid color) for this "dummy visual" phase.
- DB schema for query events + aggregated popularity stats, the scoring job, and the API shape — next to design.

### Technical design (proposed)

**`search_events`** (raw log)
| column | notes |
|---|---|
| id | PK |
| query_text | the search query |
| event_type | `search` / `product_click` / `add_to_cart` |
| product_id | nullable — only set for click/add_to_cart events |
| position | nullable — the product's rank position (1, 2, 3... 10) in that query's results when clicked/added to cart. Enables position-bias-aware analysis later (raw CTR conflates "genuinely relevant" with "just happened to be first"), not just a raw click count. |
| created_at | timestamp |

**`popular_queries`** (computed, ranked output)
`query_text`, `search_volume`, `click_rate`, `cart_rate`, `popularity_score`, `is_seed`, `rank`, `computed_at`.

**Scoring job** (script): pulls last 7 days from `search_events`, aggregates per query, log-scales volume, min-max normalizes all three metrics, applies the 1/3 weighting, applies the ≥30-volume replacement rule, writes ranked output to `popular_queries`.

**API:** `GET /api/popular-searches` (returns top-N ranked queries; frontend shuffles for display), plus `POST /api/events/search`, `/click`, `/add-to-cart` for logging.

**Resolved:** adding a stub Add to Cart action, scoped narrowly to avoid ballooning into real checkout. Each product card in the results gets an "Add to Cart" button that fires `POST /api/events/add-to-cart` (`query_text`, `product_id`, `position`) and gives a simple visual acknowledgment (button flips to "Added ✓" / a toast). No persistent cart, no checkout, no quantity management — just enough to generate real signal for the cart-rate leg of the popularity formula.

## Step 4 — AI-Led Development

**Built:**
- `CREATE_SEARCH_EVENTS_TABLES.py` — creates `search_events` and `popular_queries`, seeds the 17 launch queries.
- `COMPUTE_POPULAR_QUERIES.py` — the scoring job (log-scale + min-max normalize + 1/3 weighting + ≥30-volume replacement rule), safe to re-run any time as a full recompute.
- `backend/routes/discovery_routes.py` — `GET /api/categories/leaf` (leaf categories with products, grouped under Vegetables/Fruits/Staples), `GET /api/popular-searches`, and the three event-logging endpoints. Registered in `app.py` alongside the existing search blueprint.
- `app.py` — added a catch-all route so client-side routes (`/search`, `/results`) survive a browser refresh, not just in-app navigation.
- `backend/static/index.html` — added React Router (CDN, `BrowserRouter`) with three routes: `/` (Home — dummy visual tile grid of leaf categories under Vegetables/Fruits/Staples, search bar, delivery banner), `/search` (Popular Search chips, shuffled, plus a real text input), `/results` (the existing semantic search UI, now reading `?q=` from the URL and auto-running on load). Tapping a chip jumps straight to results per the "one tap, done" decision. Added the stub Add to Cart button and click/search event firing to the results flow; the existing Explainability panel is untouched.

**Not yet done / explicitly deferred:** real icons for category tiles (placeholder initials used for now); tile taps don't filter results yet (visual-only "dummy" phase, as scoped).

## Step 5 — Measurement

Same reality check as Step 1: no real users yet, so Measurement means (a) defining what to track once there's traffic, and (b) actually being able to compute the numbers now, even on sparse test data - not just writing definitions with nothing behind them.

**Candidates considered:** Popular Search adoption rate, per-product CTR (clicks/impressions), query abandonment rate, Popular Search list turnover (does a real query ever actually cross the ≥30-volume threshold and displace a seed?), position bias (are clicks concentrated at position 1-2 regardless of relevance?). Scoped to the first two for now; the rest are documented as good-to-have, not blocking.

**Metric 1 — Popular Search adoption rate.** What fraction of searches originate from tapping a chip vs. typing manually. Requires knowing *how* each search was initiated, which the event schema didn't originally capture - added `query_type` to `search_events`: `popular_search` (chip tap), `manual_entered` (typed), `auto_suggestion_picked` (reserved for the not-yet-built Auto Suggestion feature, so no second migration is needed later). Carried on every event tied to a search - not just the `search` event itself, but every impression/click/add-to-cart from that same results render - so engagement can be sliced by acquisition path, not just counted in aggregate.

**Metric 2 — Per-product CTR.** clicks ÷ impressions, using the `product_impression` event added earlier. Sharper than clicks ÷ searches (the original proxy) since result-set size varies per query.

**Built:**
- `ADD_QUERY_TYPE_TO_EVENTS.py` — adds the `query_type` column + CHECK constraint.
- `backend/routes/discovery_routes.py` — every event endpoint (`search`, `impressions`, `click`, `add-to-cart`) now accepts and validates `query_type`.
- `backend/static/index.html` — Search page tags chip taps as `popular_search` and typed submissions as `manual_entered`, passes `query_type` through the `/results?...&query_type=...` URL; Results page carries it in state for the lifetime of that search (search-type toggle re-runs keep it, a fresh manually-typed query on the Results page itself resets it to `manual_entered`) and stamps it onto every impression/click/add-to-cart.
- `COMPUTE_MEASUREMENT_METRICS.py` — read-only report: adoption rate breakdown, overall and per-query-type CTR/cart-rate, and a per-position CTR breakdown (a first look at position bias, using data already being collected even though that's not one of the two scoped metrics).

## Step 6 — Native AI Capability Check

**As shipped, Popular Searches has zero native AI capability.** It's pure statistics - counting, log-scaling, min-max normalizing, a hand-picked 1/3 weighting, a threshold rule. No model, no embeddings, no learned parameters. This is treated as the *correct* call given the data volume, not a gap: with the amount of real event data this app will ever plausibly generate, a learned ranking model would overfit noise rather than improve anything. Recognizing when *not* to reach for ML is as much a signal of AI product judgment as knowing when to use it.

**One place native AI genuinely earns its keep, cheaply, reusing existing infrastructure: semantic query deduplication.** "Cooking oil," "oil," and "edible oil" were 3 separate rows in `popular_queries`, each with fragmented volume/CTR, despite meaning the same thing to a shopper. Since OpenAI embeddings are already called for the core search feature, embedding each distinct query and clustering near-duplicates before aggregating stats fixes real fragmentation at near-zero marginal infrastructure cost.

**Built:**
- `CREATE_QUERY_CLUSTERING_TABLES.py` — `query_embeddings` (cache, avoids re-embedding a query already seen) and `query_aliases` (the query_text → canonical_query mapping).
- `CLUSTER_QUERIES.py` — embeds every distinct query (the 17 seeds + everything seen in `search_events`), then greedily clusters: seeds processed first (so curated labels become canonicals preferentially), then the rest by descending volume, each compared by cosine similarity against canonicals chosen so far (threshold 0.85, a starting point rather than a validated constant — short, ambiguous queries make this genuinely hard to get perfect, which is why the dry run prints every proposed merge for a sanity check before committing).
- `COMPUTE_POPULAR_QUERIES.py` — updated to aggregate `search_events` by canonical query (via `query_aliases`, falling back to the raw query if it hasn't been clustered yet) before scoring, and to clean up any old `popular_queries` row for a seed that got merged into a different canonical.

**Two other candidates, named but deliberately not built:**
- **Learned ranking model** replacing the hand-weighted formula — the right long-term evolution, but premature before there's real traffic to learn from; would overfit at current data volumes. (Full discussion below.)
- **The actual Auto Suggestion feature** (the roadmap item deferred back in Step 1/2) — "anchored in category/brand/attributes" suggestions matched semantically rather than by string prefix is where this roadmap always pointed toward real AI, more than Popular Searches itself ever was. Natural next iteration of this same framework.

## Deferred — Learned Ranking Model

**Problem.** `popularity_score = (norm_volume + norm_click + norm_cart) / 3` uses a 1/3-1/3-1/3 weighting we picked because it seemed reasonable, not because we verified it's correct. Maybe cart_rate should matter twice as much as volume, since it's closer to real purchase intent. Maybe click_rate is noisy and should count for less. We don't actually know — the weighting is an assumption, not a measured fact.

**Why it matters.** A hand-picked formula stays fixed forever unless someone manually revisits it. It can't discover that one signal is more predictive than another, can't pick up on interactions between signals (e.g. "high volume only matters if cart_rate is also decent"), and doesn't adapt as customer behavior shifts over time.

**Solution, conceptually.** This is "Learning to Rank" (LTR) — a well-established ML subfield, how search engines and marketplaces have ranked results for two decades:
1. Pick a label - the actual outcome to predict (e.g. "did this query lead to a purchase"), not "does it look popular by our formula."
2. Turn signals into features - log_volume, click_rate, cart_rate, recency, maybe query length or result-set diversity.
3. Train a model (often logistic regression, or gradient-boosted trees like XGBoost - the industry-standard for LTR) on historical examples, letting it find the weights itself instead of us hand-picking 1/3 each.
4. The trained model replaces the fixed formula - same inputs, learned combination instead of an assumed one.

**Why it's premature here.** Models need enough real examples to learn a genuine pattern instead of memorizing noise. Rough industry rule of thumb: hundreds of labeled examples per feature, even for a simple model. This app currently has maybe a few dozen queries and a handful of manually-generated test events - any model trained today would just fit our own test clicks, not a real pattern. The heuristic is, ironically, more robust at this data volume precisely because it doesn't try to learn from too little.

**Right sequencing:** ship the heuristic now (deliberately robust at low data volume) → collect real events over time → revisit with a learned model once there's enough traffic to make training meaningful.

## Auto Suggestion — Second Iteration of the Framework

The actual as-you-type Auto Suggestion feature (deferred back in Step 1/2), now being framed and built. Per the roadmap: typing "milk" should surface "Milk Nandhini," "Organic Milk," "A2 Milk," "Milk Packet 1kg" — suggestions shaped `<category>, <brand>, <type>, <attributes>`, built as the customer types.

### Approach considered and rejected: precomputed combination vocabulary

First idea: extract every distinct (category × brand), (category × organic), (category × variety), (category × pack_size) combination that actually occurs in the product data, embed each as its own suggestion string, and match the typed text against that.

**Why it doesn't fully work:** it only ever adds *one* facet on top of category. It breaks the moment a customer has already typed two facets themselves - e.g. "nandhini milk" (brand + category already specified) - and needs a *third* facet suggested ("Nandhini Milk 500ml," "Nandhini Full Toned Milk"). Precomputing every possible combination to handle that would mean embedding every 1-way, 2-way, 3-way, and 4-way combination of facets up front - a combinatorially large, constantly-growing vocabulary, most of which would rarely be used.

### Final design: separate "recognizing terms" from "combining them"

**Which facets need semantic matching at all.** Category and brand have open-ended vocabularies where people phrase things differently ("milk" vs "dairy") - these benefit from embeddings. Organic is a boolean (simple keyword check for "organic" in the typed text) and pack_size is a number+unit pattern (`\d+\s?(ml|l|kg|g)`, simple regex) - neither needs embeddings at all.

**Offline (one-time + daily delta) - build a small, flat vocabulary, not combinations:**
1. Distinct-value queries per facet: distinct category names, distinct brands, distinct variety values.
2. Embed each distinct term once (only category/brand/variety - not organic or pack_size).
3. Daily delta via hash-diff (same pattern as query clustering): re-run the same distinct queries against today's live data, hash each term. New hash → embed + insert. Hash that existed yesterday but not today → mark `is_active = false` (soft delete, cheap to revive). Same hash both days → skip, no re-embedding. This one mechanism transparently handles new products, deleted products, *and* updated products (a changed attribute just makes an old combo disappear and a new one appear - no special-case code needed for "update").

**Online (per keystroke, after a debounce) - no embedding calls in the live path at all:**
1. Cheap deterministic checks first: keyword search for "organic," regex for pack size.
2. Facet recognition for category/brand via **Postgres trigram similarity (`pg_trgm`)**, not live embedding calls - fuzzy, indexed, near-instant (single-digit ms), handles typos and partial words. This was a deliberate latency fix: embedding the customer's typed text via OpenAI on every keystroke pause would cost 100-500ms+ per call (a network round trip), which is too slow for autosuggest (compare Google/Amazon, both well under 100ms). Trigram matching won't catch true synonyms the way embeddings would, but for recognizing known catalog-specific brand/category strings specifically, it's normally good enough, and it's local to the database - no external API call in the hot path.
3. Once facets-so-far are known (e.g. category=Milk, brand=Nandhini), run a live, indexed SQL drill-down: `SELECT DISTINCT pack_size, organic, variety FROM products JOIN product_attributes ... WHERE category='Milk' AND brand='Nandhini'` - fast because `category`/`brand` are already indexed columns.
4. Format each result by combining the already-recognized facets with each newly-found value ("Nandhini Milk 500ml," "Nandhini Full Toned Milk"), rank/limit, return.

So embeddings are used **only in the offline vocabulary build**, where speed doesn't matter (a nightly batch job); the live per-keystroke path is pure SQL (trigram match + indexed filter), which is what actually makes it fast enough to use.

### Built

- `CREATE_SUGGESTION_VOCABULARY_TABLE.py` — enables `pg_trgm`, creates `suggestion_vocabulary` (`term_text`, `facet_type` ∈ category/brand/variety, `embedding`, `is_active`), with a GIN trigram index on `term_text` for the live matching and a `UNIQUE(facet_type, term_text)` constraint as the natural dedup key.
- `GENERATE_SUGGESTION_VOCABULARY.py` — the one script that serves both "one-time generation" and "daily delta": pulls current distinct category names / brands / variety values straight from the catalog, diffs against what's already in `suggestion_vocabulary`, embeds only genuinely new terms, reactivates any that disappeared and came back (no re-embedding needed), deactivates ones no longer present, and skips everything unchanged entirely - so a full backfill and a daily refresh are the exact same command.
- `backend/routes/autosuggest_routes.py` — `GET /api/auto-suggest?q=...`. No embedding calls anywhere in this file: `word_similarity()` (pg_trgm) finds the best-matching category/brand for the typed text, a keyword check catches "organic," a regex catches pack sizes (`\d+\s?(ml|l|kg|g)`), then a live `SELECT DISTINCT` drill-down (filtered on whatever facets were recognized) returns the actual remaining facet values that exist in the catalog, formatted into suggestion strings that fold in only the *new* facets rather than repeating what was already typed.
- `backend/static/index.html` — the Search page's input is now debounced (250ms) against `/api/auto-suggest`; once the customer has typed ≥2 characters and suggestions come back, the chip list swaps from Popular Searches to live Auto Suggestions. Tapping one logs `query_type=auto_suggestion_picked` (the value reserved back in Step 5) and jumps straight to Results, same "one tap, done" pattern as Popular Search chips.
