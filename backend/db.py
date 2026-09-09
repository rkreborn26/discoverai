"""
DiscoverAI Backend: Database Connection Pool
=============================================

Provides pooled connections to Neon Postgres instead of one global
connection (which is what the tutorial/debug scripts used). A pool is
required here because a web server handles multiple requests, possibly
concurrently, and a single shared connection isn't safe for that.

The pool is created lazily on first use, not at import time, so the
Flask app can boot (and routes like /api/health can respond) even
before anything actually needs the database.
"""

import os
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool as pg_pool
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

_pool = None


def _get_pool():
    """Create the connection pool on first use (lazy init)."""
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL not set. Make sure .env exists and contains DATABASE_URL."
            )
        _pool = pg_pool.SimpleConnectionPool(
            minconn=1,
            maxconn=5,
            dsn=DATABASE_URL,
        )
    return _pool


@contextmanager
def get_cursor(commit=False):
    """
    Context manager that hands out a cursor from the pool and always
    returns the connection when done, even if an error occurs.

    Usage:
        with get_cursor() as cur:
            cur.execute("SELECT ...")
            rows = cur.fetchall()

    Set commit=True for INSERT/UPDATE/DELETE statements.
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        pool.putconn(conn)


def health_check():
    """Quick check used by /api/health - confirms the DB is reachable."""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
        return True
    except Exception as e:
        return False
