-- ============================================================
-- DiscoverAI Database Schema
-- Auto-generated from Neon via get_schema.py
-- ============================================================

-- Extensions
-- ----------
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- v1.6 on source db
CREATE EXTENSION IF NOT EXISTS "vector";  -- v0.8.0 on source db

-- ------------------------------------------------------------
-- TABLE: cart_items
-- ------------------------------------------------------------
-- Row count: 0
CREATE SEQUENCE IF NOT EXISTS "cart_items_id_seq";

CREATE TABLE IF NOT EXISTS cart_items (
    id bigint PRIMARY KEY DEFAULT nextval('cart_items_id_seq'::regclass),
    persona_id character varying(50) NOT NULL,
    product_id character varying(50) NOT NULL,  -- FK -> products.id
    quantity integer NOT NULL DEFAULT 1,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

ALTER SEQUENCE "cart_items_id_seq" OWNED BY "cart_items"."id";

-- Indexes on cart_items:
-- CREATE UNIQUE INDEX cart_items_pkey ON public.cart_items USING btree (id);
-- CREATE UNIQUE INDEX cart_items_persona_id_product_id_key ON public.cart_items USING btree (persona_id, product_id);
-- CREATE INDEX idx_cart_items_persona ON public.cart_items USING btree (persona_id);

-- ------------------------------------------------------------
-- TABLE: categories
-- ------------------------------------------------------------
-- Row count: 142
CREATE TABLE IF NOT EXISTS categories (
    id character varying(50) PRIMARY KEY,
    category_code character varying(50) NOT NULL,
    name character varying(100) NOT NULL,
    parent_id character varying(50),  -- FK -> categories.id
    level integer NOT NULL,
    path character varying(500),
    icon_url character varying(500),
    description text,
    display_order integer DEFAULT 0,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

-- Indexes on categories:
-- CREATE UNIQUE INDEX categories_category_code_key ON public.categories USING btree (category_code);
-- CREATE UNIQUE INDEX categories_pkey ON public.categories USING btree (id);
-- CREATE INDEX idx_category_code ON public.categories USING btree (category_code);
-- CREATE INDEX idx_is_active ON public.categories USING btree (is_active);
-- CREATE INDEX idx_level ON public.categories USING btree (level);
-- CREATE INDEX idx_parent_id ON public.categories USING btree (parent_id);

-- ------------------------------------------------------------
-- TABLE: category_suggestion_phrases
-- ------------------------------------------------------------
-- Row count: 362
CREATE SEQUENCE IF NOT EXISTS "category_suggestion_phrases_id_seq";

CREATE TABLE IF NOT EXISTS category_suggestion_phrases (
    id bigint PRIMARY KEY DEFAULT nextval('category_suggestion_phrases_id_seq'::regclass),
    category character varying(255) NOT NULL,
    phrase_text character varying(255) NOT NULL,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

ALTER SEQUENCE "category_suggestion_phrases_id_seq" OWNED BY "category_suggestion_phrases"."id";

-- Indexes on category_suggestion_phrases:
-- CREATE UNIQUE INDEX category_suggestion_phrases_pkey ON public.category_suggestion_phrases USING btree (id);
-- CREATE UNIQUE INDEX category_suggestion_phrases_category_phrase_text_key ON public.category_suggestion_phrases USING btree (category, phrase_text);
-- CREATE INDEX idx_category_suggestion_phrases_trgm ON public.category_suggestion_phrases USING gin (phrase_text gin_trgm_ops);
-- CREATE INDEX idx_category_suggestion_phrases_active ON public.category_suggestion_phrases USING btree (is_active);

-- ------------------------------------------------------------
-- TABLE: order_items
-- ------------------------------------------------------------
-- Row count: 111
CREATE SEQUENCE IF NOT EXISTS "order_items_id_seq";

CREATE TABLE IF NOT EXISTS order_items (
    id bigint PRIMARY KEY DEFAULT nextval('order_items_id_seq'::regclass),
    order_id character varying(50) NOT NULL,  -- FK -> orders.id
    product_id character varying(50) NOT NULL,  -- FK -> products.id
    product_name character varying(255) NOT NULL,
    brand character varying(100),
    price numeric(12,2) NOT NULL,
    quantity integer NOT NULL,
    image_url character varying(500),
    pack_size character varying(50)
);

ALTER SEQUENCE "order_items_id_seq" OWNED BY "order_items"."id";

-- Indexes on order_items:
-- CREATE UNIQUE INDEX order_items_pkey ON public.order_items USING btree (id);
-- CREATE INDEX idx_order_items_order ON public.order_items USING btree (order_id);

-- ------------------------------------------------------------
-- TABLE: orders
-- ------------------------------------------------------------
-- Row count: 98
CREATE TABLE IF NOT EXISTS orders (
    id character varying(50) PRIMARY KEY,
    persona_id character varying(50) NOT NULL,
    status character varying(30) NOT NULL DEFAULT 'Placed'::character varying,
    total_amount numeric(12,2) NOT NULL,
    placed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

-- Indexes on orders:
-- CREATE UNIQUE INDEX orders_pkey ON public.orders USING btree (id);
-- CREATE INDEX idx_orders_persona ON public.orders USING btree (persona_id, placed_at DESC);

-- ------------------------------------------------------------
-- TABLE: popular_queries
-- ------------------------------------------------------------
-- Row count: 17
CREATE TABLE IF NOT EXISTS popular_queries (
    query_text character varying(255) PRIMARY KEY,
    search_volume integer DEFAULT 0,
    click_rate numeric(6,4) DEFAULT 0,
    cart_rate numeric(6,4) DEFAULT 0,
    popularity_score numeric(6,4) DEFAULT 0,
    is_seed boolean DEFAULT false,
    rank integer,
    computed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

-- Indexes on popular_queries:
-- CREATE UNIQUE INDEX popular_queries_pkey ON public.popular_queries USING btree (query_text);

-- ------------------------------------------------------------
-- TABLE: product_attributes
-- ------------------------------------------------------------
-- Row count: 2427
CREATE TABLE IF NOT EXISTS product_attributes (
    id character varying(50) PRIMARY KEY,
    product_id character varying(50) NOT NULL,  -- FK -> products.id
    pack_size character varying(50),
    organic boolean,
    color character varying(50),
    size character varying(20),
    material character varying(100),
    fit_type character varying(50),
    ram_gb integer,
    storage_gb integer,
    connectivity_5g boolean,
    processor character varying(100),
    display_size_inch double precision,
    attributes json DEFAULT '{}'::json,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    quantity numeric(10,2),
    unit character varying(10)
);

-- Indexes on product_attributes:
-- CREATE UNIQUE INDEX product_attributes_pkey ON public.product_attributes USING btree (id);
-- CREATE UNIQUE INDEX product_attributes_product_id_key ON public.product_attributes USING btree (product_id);
-- CREATE INDEX idx_color ON public.product_attributes USING btree (color);
-- CREATE INDEX idx_connectivity_5g ON public.product_attributes USING btree (connectivity_5g);
-- CREATE INDEX idx_organic ON public.product_attributes USING btree (organic);
-- CREATE INDEX idx_pack_size ON public.product_attributes USING btree (pack_size);
-- CREATE INDEX idx_ram_gb ON public.product_attributes USING btree (ram_gb);
-- CREATE INDEX idx_storage_gb ON public.product_attributes USING btree (storage_gb);

-- ------------------------------------------------------------
-- TABLE: product_review_summaries
-- ------------------------------------------------------------
-- Row count: 1
CREATE TABLE IF NOT EXISTS product_review_summaries (
    id character varying(50) PRIMARY KEY,
    product_id character varying(50) NOT NULL,  -- FK -> products.id
    draft_text text,
    published_text text,
    review_count_at_generation integer,
    is_edited boolean NOT NULL DEFAULT false,
    generated_at timestamp without time zone,
    published_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

-- Indexes on product_review_summaries:
-- CREATE UNIQUE INDEX product_review_summaries_pkey ON public.product_review_summaries USING btree (id);
-- CREATE UNIQUE INDEX product_review_summaries_product_id_key ON public.product_review_summaries USING btree (product_id);

-- ------------------------------------------------------------
-- TABLE: product_reviews
-- ------------------------------------------------------------
-- Row count: 111
CREATE TABLE IF NOT EXISTS product_reviews (
    id character varying(50) PRIMARY KEY,
    product_id character varying(50) NOT NULL,  -- FK -> products.id
    persona_id character varying(50) NOT NULL,
    rating integer NOT NULL,
    review_text text,
    status character varying(20) NOT NULL DEFAULT 'submitted'::character varying,
    rejection_reason character varying(30),
    moderated_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    rejection_note text,
    ai_decision character varying(20),
    ai_rejection_reason character varying(50),
    ai_note text,
    ai_confidence numeric(3,2),
    ai_agent_trace jsonb,
    ai_moderated_at timestamp without time zone,
    moderator_agreed boolean
);

-- Indexes on product_reviews:
-- CREATE UNIQUE INDEX product_reviews_pkey ON public.product_reviews USING btree (id);
-- CREATE UNIQUE INDEX product_reviews_product_id_persona_id_key ON public.product_reviews USING btree (product_id, persona_id);
-- CREATE INDEX idx_product_reviews_product ON public.product_reviews USING btree (product_id);
-- CREATE INDEX idx_product_reviews_status ON public.product_reviews USING btree (status);

-- ------------------------------------------------------------
-- TABLE: products
-- ------------------------------------------------------------
-- Row count: 2598
CREATE TABLE IF NOT EXISTS products (
    id character varying(50) PRIMARY KEY,
    sku character varying(100) NOT NULL,
    name character varying(255) NOT NULL,
    category character varying(50) NOT NULL,
    brand character varying(100),
    price numeric(12,2) NOT NULL,
    original_price numeric(12,2),
    discount_percentage integer,
    in_stock boolean DEFAULT true,
    stock_quantity integer DEFAULT 0,
    image_url character varying(500),
    description text,
    rating double precision DEFAULT 0.0,
    review_count integer DEFAULT 0,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    deleted_at timestamp without time zone,
    embedding vector,
    embedding_full vector,
    embedding_category vector,
    embedding_name vector
);

-- Indexes on products:
-- CREATE UNIQUE INDEX products_pkey ON public.products USING btree (id);
-- CREATE UNIQUE INDEX products_sku_key ON public.products USING btree (sku);
-- CREATE INDEX idx_brand ON public.products USING btree (brand);
-- CREATE INDEX idx_category ON public.products USING btree (category);
-- CREATE INDEX idx_in_stock ON public.products USING btree (in_stock);
-- CREATE INDEX idx_sku ON public.products USING btree (sku);
-- CREATE INDEX idx_products_embedding ON public.products USING ivfflat (embedding vector_cosine_ops) WITH (lists='100');
-- CREATE INDEX idx_embedding_full ON public.products USING ivfflat (embedding_full vector_cosine_ops) WITH (lists='100');
-- CREATE INDEX idx_embedding_category ON public.products USING ivfflat (embedding_category vector_cosine_ops) WITH (lists='100');
-- CREATE INDEX idx_embedding_name ON public.products USING ivfflat (embedding_name vector_cosine_ops) WITH (lists='100');

-- ------------------------------------------------------------
-- TABLE: query_aliases
-- ------------------------------------------------------------
-- Row count: 24
CREATE TABLE IF NOT EXISTS query_aliases (
    query_text character varying(255) PRIMARY KEY,
    canonical_query character varying(255) NOT NULL,
    similarity numeric(6,4),
    computed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

-- Indexes on query_aliases:
-- CREATE UNIQUE INDEX query_aliases_pkey ON public.query_aliases USING btree (query_text);

-- ------------------------------------------------------------
-- TABLE: query_embeddings
-- ------------------------------------------------------------
-- Row count: 24
CREATE TABLE IF NOT EXISTS query_embeddings (
    query_text character varying(255) PRIMARY KEY,
    embedding vector,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

-- Indexes on query_embeddings:
-- CREATE UNIQUE INDEX query_embeddings_pkey ON public.query_embeddings USING btree (query_text);

-- ------------------------------------------------------------
-- TABLE: review_images
-- ------------------------------------------------------------
-- Row count: 0
CREATE TABLE IF NOT EXISTS review_images (
    id character varying(50) PRIMARY KEY,
    review_id character varying(50) NOT NULL,  -- FK -> product_reviews.id
    image_url character varying(500) NOT NULL,
    file_size_bytes integer,
    position integer NOT NULL DEFAULT 0,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

-- Indexes on review_images:
-- CREATE UNIQUE INDEX review_images_pkey ON public.review_images USING btree (id);
-- CREATE INDEX idx_review_images_review ON public.review_images USING btree (review_id);

-- ------------------------------------------------------------
-- TABLE: search_events
-- ------------------------------------------------------------
-- Row count: 432
CREATE SEQUENCE IF NOT EXISTS "search_events_id_seq";

CREATE TABLE IF NOT EXISTS search_events (
    id bigint PRIMARY KEY DEFAULT nextval('search_events_id_seq'::regclass),
    query_text character varying(255) NOT NULL,
    event_type character varying(20) NOT NULL,
    product_id character varying(50),  -- FK -> products.id
    position integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    query_type character varying(30)
);

ALTER SEQUENCE "search_events_id_seq" OWNED BY "search_events"."id";

-- Indexes on search_events:
-- CREATE UNIQUE INDEX search_events_pkey ON public.search_events USING btree (id);
-- CREATE INDEX idx_search_events_query_text ON public.search_events USING btree (query_text);
-- CREATE INDEX idx_search_events_created_at ON public.search_events USING btree (created_at);
-- CREATE INDEX idx_search_events_event_type ON public.search_events USING btree (event_type);

-- ------------------------------------------------------------
-- TABLE: suggestion_vocabulary
-- ------------------------------------------------------------
-- Row count: 505
CREATE SEQUENCE IF NOT EXISTS "suggestion_vocabulary_id_seq";

CREATE TABLE IF NOT EXISTS suggestion_vocabulary (
    id bigint PRIMARY KEY DEFAULT nextval('suggestion_vocabulary_id_seq'::regclass),
    term_text character varying(255) NOT NULL,
    facet_type character varying(20) NOT NULL,
    embedding vector,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

ALTER SEQUENCE "suggestion_vocabulary_id_seq" OWNED BY "suggestion_vocabulary"."id";

-- Indexes on suggestion_vocabulary:
-- CREATE UNIQUE INDEX suggestion_vocabulary_pkey ON public.suggestion_vocabulary USING btree (id);
-- CREATE UNIQUE INDEX suggestion_vocabulary_facet_type_term_text_key ON public.suggestion_vocabulary USING btree (facet_type, term_text);
-- CREATE INDEX idx_suggestion_vocab_trgm ON public.suggestion_vocabulary USING gin (term_text gin_trgm_ops);
-- CREATE INDEX idx_suggestion_vocab_active ON public.suggestion_vocabulary USING btree (facet_type, is_active);
