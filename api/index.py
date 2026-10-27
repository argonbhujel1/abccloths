"""
ABC Clothing — Flask backend for Vercel Python runtime.
Handles products, settings, notices, orders, contact, and admin auth.
"""

import os
import json
import re
import secrets
import hashlib
import hmac
import time
from datetime import datetime, timezone, timedelta
from functools import wraps
from urllib.parse import urlparse
from pathlib import Path

from flask import (
    send_from_directory,
    Flask, request, jsonify, session, redirect, url_for,
    make_response, render_template, render_template_string, abort
)
from werkzeug.security import generate_password_hash, check_password_hash

# Optional imports — fail gracefully if missing in local testing without deps
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load .env from project root (parent of api/) or cwd — local development
try:
    from dotenv import load_dotenv
    _root = Path(__file__).resolve().parent.parent
    load_dotenv(_root / ".env")
    load_dotenv()  # also cwd
except Exception:
    pass

_BASE = Path(__file__).resolve().parent.parent
_TPL = _BASE / "templates"
if not _TPL.is_dir():
    _TPL = Path(__file__).resolve().parent / "templates"
PUBLIC_DIR = Path(__file__).resolve().parent / "public"
if not PUBLIC_DIR.is_dir():
    PUBLIC_DIR = _BASE / "public"
if not PUBLIC_DIR.is_dir():
    PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
app = Flask(__name__, template_folder=str(_TPL), static_folder=str(PUBLIC_DIR), static_url_path="")
app.secret_key = os.environ.get("SESSION_SECRET", secrets.token_hex(32))


@app.route("/css/<path:filename>")
def serve_css(filename):
    resp = send_from_directory(str(PUBLIC_DIR / "css"), filename)
    resp.headers["Content-Type"] = "text/css; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/js/<path:filename>")
def serve_js(filename):
    resp = send_from_directory(str(PUBLIC_DIR / "js"), filename)
    if filename.endswith(".json"):
        resp.headers["Content-Type"] = "application/json; charset=utf-8"
    else:
        resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/assets/<path:filename>")
def serve_assets(filename):
    return send_from_directory(str(PUBLIC_DIR / "assets"), filename)


app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("VERCEL")),
    SESSION_COOKIE_NAME="abc_admin_session",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,  # 2 MB
)

# Nepal Standard Time offset
NPT = timezone(timedelta(hours=5, minutes=45))

def load_category_tree():
    paths = [
        Path(__file__).resolve().parent / "category-tree.json",
        Path(__file__).resolve().parent.parent / "public" / "js" / "categories.js",
    ]
    for p in paths:
        if p.suffix == ".json" and p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}

CATEGORY_TREE = load_category_tree()


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db_url():
    return os.environ.get("DATABASE_URL", "").strip()


_schema_ready = False

def get_db_urls():
    """Primary + optional backup Neon URLs from env."""
    primary = os.environ.get("DATABASE_URL", "").strip()
    backup = os.environ.get("DATABASE_URL_BACKUP", "").strip()
    urls = []
    if primary:
        urls.append(("primary", primary))
    if backup and backup != primary:
        urls.append(("backup", backup))
    return urls


def get_db_url():
    urls = get_db_urls()
    return urls[0][1] if urls else ""


def _normalize_db_url(url):
    if "sslmode=" not in url and ("neon.tech" in url or "amazonaws.com" in url):
        url = url + ("&" if "?" in url else "?") + "sslmode=require"
    return url


def get_connection():
    global _schema_ready
    if not HAS_PSYCOPG2:
        return None
    urls = get_db_urls()
    if not urls:
        return None
    last_err = None
    for label, raw in urls:
        url = _normalize_db_url(raw)
        try:
            conn = psycopg2.connect(url, connect_timeout=5)
            conn.autocommit = True
            try:
                with conn.cursor() as cur:
                    cur.execute("SET statement_timeout = 8000")
            except Exception:
                pass
            app.config["_db_active"] = label
            if not _schema_ready:
                try:
                    init_schema(conn)
                    ensure_admin_user(conn)
                    _schema_ready = True
                except Exception as e:
                    app.config["_last_db_error"] = str(e)[:200]
            return conn
        except Exception as e:
            last_err = e
            continue
    if last_err:
        app.config["_last_db_error"] = str(last_err)[:200]
    return None


def init_schema(conn):
    """Create tables if they do not exist. Safe to call multiple times."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                price INTEGER NOT NULL CHECK (price >= 0),
                image_url TEXT DEFAULT '',
                description TEXT DEFAULT '',
                category VARCHAR(50) DEFAULT 'men',
                subcategory VARCHAR(80) DEFAULT '',
                product_type VARCHAR(80) DEFAULT '',
                variant VARCHAR(80) DEFAULT '',
                colors TEXT DEFAULT '[]',
                sizes TEXT DEFAULT '[]',
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS website_settings (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                logo_url TEXT DEFAULT '',
                favicon_url TEXT DEFAULT '',
                brand_name VARCHAR(120) DEFAULT 'Atelier Lane',
                facebook_url TEXT DEFAULT '',
                instagram_url TEXT DEFAULT '',
                whatsapp TEXT DEFAULT '',
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            INSERT INTO website_settings (id) VALUES (1)
            ON CONFLICT (id) DO NOTHING
        """)
        for col, typ in (
            ("brand_name", "VARCHAR(120)"),
            ("facebook_url", "TEXT"),
            ("instagram_url", "TEXT"),
            ("whatsapp", "TEXT"),
            ("logo_url", "TEXT"),
            ("favicon_url", "TEXT"),
        ):
            try:
                cur.execute(
                    f"ALTER TABLE website_settings ADD COLUMN IF NOT EXISTS {col} {typ}"
                )
            except Exception:
                pass
        for col, typ in (
            ("subcategory", "VARCHAR(80)"),
            ("product_type", "VARCHAR(80)"),
            ("variant", "VARCHAR(80)"),
            ("image_url", "TEXT"),
            ("description", "TEXT"),
            ("colors", "TEXT"),
            ("sizes", "TEXT"),
            ("active", "BOOLEAN"),
        ):
            try:
                cur.execute(
                    f"ALTER TABLE products ADD COLUMN IF NOT EXISTS {col} {typ}"
                )
            except Exception:
                pass
        cur.execute("""
            CREATE TABLE IF NOT EXISTS team_members (
                id SERIAL PRIMARY KEY,
                team_type VARCHAR(20) NOT NULL,
                name VARCHAR(150) NOT NULL,
                role VARCHAR(200) DEFAULT '',
                bio TEXT DEFAULT '',
                photo_url TEXT DEFAULT '',
                enabled BOOLEAN DEFAULT TRUE,
                sort_order INTEGER DEFAULT 0,
                locked BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS homepage_notice (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                title VARCHAR(200) DEFAULT '',
                message TEXT DEFAULT '',
                image_url TEXT DEFAULT '',
                button_text VARCHAR(100) DEFAULT '',
                button_url TEXT DEFAULT '',
                notice_type VARCHAR(20) DEFAULT 'banner',
                enabled BOOLEAN DEFAULT FALSE,
                start_date DATE,
                end_date DATE,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            INSERT INTO homepage_notice (id) VALUES (1)
            ON CONFLICT (id) DO NOTHING
        """)
        try:
            cur.execute("SELECT COUNT(*) FROM team_members WHERE team_type = 'developer'")
            if cur.fetchone()[0] == 0:
                for name, role, order in (
                    ("Argon Bhujel", "Full stack web & Android APK developer", 1),
                    ("Manzil Bhujel", "Front end developer & data analyst", 2),
                    ("Dikshya Khanal", "Front end developer", 3),
                    ("Tularam Limbu", "UI/UX designer", 4),
                ):
                    cur.execute(
                        """INSERT INTO team_members
                           (team_type, name, role, enabled, sort_order, locked)
                           VALUES ('developer', %s, %s, TRUE, %s, TRUE)""",
                        (name, role, order),
                    )
        except Exception:
            pass
        cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                order_ref VARCHAR(32) UNIQUE NOT NULL,
                customer_name VARCHAR(150) NOT NULL,
                customer_email VARCHAR(200) NOT NULL,
                customer_phone VARCHAR(40) NOT NULL,
                address TEXT NOT NULL,
                city VARCHAR(100) NOT NULL,
                notes TEXT DEFAULT '',
                items JSONB NOT NULL,
                total INTEGER NOT NULL,
                status VARCHAR(30) DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(80) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS login_attempts (
                ip VARCHAR(45) PRIMARY KEY,
                attempts INTEGER DEFAULT 0,
                last_attempt TIMESTAMPTZ DEFAULT NOW()
            )
        """)


def ensure_admin_user(conn):
    """Create or sync initial admin from env vars."""
    username = os.environ.get("INITIAL_ADMIN_USERNAME", "").strip()
    password = os.environ.get("INITIAL_ADMIN_PASSWORD", "").strip()
    if not username or not password:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, password_hash FROM admin_users WHERE username = %s", (username,))
            row = cur.fetchone()
            pw_hash = generate_password_hash(password)
            if not row:
                cur.execute(
                    "INSERT INTO admin_users (username, password_hash) VALUES (%s, %s)",
                    (username, pw_hash),
                )
            else:
                # Keep env password as source of truth for the bootstrap admin
                try:
                    if not check_password_hash(row[1], password):
                        cur.execute(
                            "UPDATE admin_users SET password_hash = %s WHERE id = %s",
                            (pw_hash, row[0]),
                        )
                except Exception:
                    cur.execute(
                        "UPDATE admin_users SET password_hash = %s WHERE id = %s",
                        (pw_hash, row[0]),
                    )
    except Exception:
        pass


def db_available():
    conn = get_connection()
    if not conn:
        return False
    try:
        init_schema(conn)
        ensure_admin_user(conn)
        conn.close()
        return True
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def validate_csrf():
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    expected = session.get("_csrf", "")
    if not expected or not hmac.compare_digest(token, expected):
        return False
    return True


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect("/siteadmin/login/admin")
        return f(*args, **kwargs)
    return decorated


def check_rate_limit(ip):
    """Simple in-DB rate limiting for login. Returns True if allowed."""
    conn = get_connection()
    if not conn:
        return True  # allow if DB down (admin can't do much anyway)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT attempts, last_attempt FROM login_attempts WHERE ip = %s",
                (ip,),
            )
            row = cur.fetchone()
            now = datetime.now(timezone.utc)
            if row:
                attempts, last = row
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if (now - last).total_seconds() > 900:  # 15 min window
                    cur.execute(
                        "UPDATE login_attempts SET attempts = 1, last_attempt = %s WHERE ip = %s",
                        (now, ip),
                    )
                    return True
                if attempts >= 8:
                    return False
                cur.execute(
                    "UPDATE login_attempts SET attempts = attempts + 1, last_attempt = %s WHERE ip = %s",
                    (now, ip),
                )
            else:
                cur.execute(
                    "INSERT INTO login_attempts (ip, attempts, last_attempt) VALUES (%s, 1, %s)",
                    (ip, now),
                )
            return True
    except Exception:
        return True
    finally:
        try:
            conn.close()
        except Exception:
            pass


def reset_rate_limit(ip):
    conn = get_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM login_attempts WHERE ip = %s", (ip,))
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def normalize_image_url(url):
    """Clean image URL; prefer direct ImgBB i.ibb.co links."""
    if not url or not isinstance(url, str):
        return ""
    url = url.strip().strip('"').strip("'")
    # Common paste mistakes
    if url.startswith("//"):
        url = "https:" + url
    # ImgBB share page → user must use direct link; keep as-is if already i.ibb.co
    if "ibb.co/" in url and "i.ibb.co" not in url and "/gallery/" not in url:
        # leave page URL — still allow if https; browser may not show as img
        pass
    return url[:1000]


def is_safe_image_url(url):
    if not url or not isinstance(url, str):
        return False
    url = normalize_image_url(url)
    if not url or len(url) > 1000:
        return False
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            return False
        if not parsed.netloc:
            return False
        host = parsed.netloc.lower()
        # block javascript etc already handled by scheme
        if host in ("localhost", "127.0.0.1"):
            return True  # local dev
        return True
    except Exception:
        return False


def sanitize_str(val, max_len=500):
    if val is None:
        return ""
    s = str(val).strip()
    return s[:max_len]


def parse_json_list(val, default=None):
    if default is None:
        default = []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            data = json.loads(val)
            return data if isinstance(data, list) else default
        except Exception:
            return default
    return default


# ---------------------------------------------------------------------------
# API: Health
# ---------------------------------------------------------------------------


@app.route("/api/categories")
def api_categories():
    return jsonify(CATEGORY_TREE or {})

@app.route("/api/health")
def health():
    db_ok = bool(get_connection())
    payload = {
        "status": "ok",
        "database": "connected" if db_ok else "unavailable",
        "db_active": app.config.get("_db_active"),
        "has_database_url": bool(os.environ.get("DATABASE_URL", "").strip()),
        "has_database_url_backup": bool(os.environ.get("DATABASE_URL_BACKUP", "").strip()),
        "has_smtp": bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USER")),
        "has_psycopg2": HAS_PSYCOPG2,
        "timestamp": datetime.now(NPT).isoformat(),
    }
    if not db_ok:
        err = app.config.get("_last_db_error")
        if err:
            safe = re.sub(r":[^:@/]+@", ":***@", err)
            payload["db_error_hint"] = safe
    return jsonify(payload)


# ---------------------------------------------------------------------------
# API: Products (public read)
# ---------------------------------------------------------------------------

@app.route("/api/products", methods=["GET"])
def get_products():
    """Admin + public product list. Seeds catalog when DB empty; else fallback JSON."""
    def fallback_list():
        return [product_row_dict(p) for p in (_load_fallback_catalog() or [])]

    conn = get_connection()
    if not conn:
        return jsonify({
            "products": fallback_list(),
            "source": "fallback",
            "error": "database_unavailable",
            "message": "Showing catalog. Connect DATABASE_URL then use Import to edit permanently.",
        }), 200
    try:
        init_schema(conn)
        try:
            seed_catalog_if_empty(conn)
        except Exception:
            pass
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                cur.execute("""
                    SELECT id, name, price, image_url, description, category,
                           subcategory, product_type, variant,
                           colors, sizes, active, created_at, updated_at
                    FROM products
                    ORDER BY id DESC
                """)
            except Exception:
                cur.execute("""
                    SELECT id, name, price, image_url, description, category,
                           colors, sizes, active
                    FROM products
                    ORDER BY id DESC
                """)
            rows = cur.fetchall()
        products = []
        for r in rows:
            try:
                products.append(product_row_dict(r))
            except Exception:
                continue
        if not products:
            products = fallback_list()
            return jsonify({"products": products, "source": "fallback", "message": "DB empty — showing catalog"})
        return jsonify({"products": products, "source": "live", "count": len(products)})
    except Exception as e:
        return jsonify({
            "products": fallback_list(),
            "source": "fallback",
            "error": str(e)[:120],
        }), 200
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.route("/api/products", methods=["POST"])
@login_required
def create_product():
    if not validate_csrf():
        return jsonify({"error": "Invalid CSRF token"}), 403
    conn = get_connection()
    if not conn:
        return jsonify({"error": "Database unavailable. Changes cannot be saved."}), 503
    try:
        data = request.get_json(silent=True) or {}
        name = sanitize_str(data.get("name"), 200)
        price = data.get("price")
        image_url = normalize_image_url(sanitize_str(data.get("image_url"), 1000))
        description = sanitize_str(data.get("description"), 2000)
        category = sanitize_str(data.get("category"), 50) or "men"
        subcategory = sanitize_str(data.get("subcategory"), 80)
        product_type = sanitize_str(data.get("product_type"), 80)
        variant = sanitize_str(data.get("variant"), 80)
        colors = data.get("colors", [])
        sizes = data.get("sizes", [])
        active = bool(data.get("active", True))

        if not name:
            return jsonify({"error": "Product name is required"}), 400
        try:
            price = int(price)
            if price < 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Valid price (NPR) is required"}), 400
        if image_url and not is_safe_image_url(image_url):
            return jsonify({"error": "Invalid image URL"}), 400

        colors_json = json.dumps(colors if isinstance(colors, list) else [])
        sizes_json = json.dumps(sizes if isinstance(sizes, list) else [])

        init_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO products (name, price, image_url, description, category, subcategory, product_type, variant, colors, sizes, active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, price, image_url, description, category, subcategory, product_type, variant, colors, sizes, active
            """, (name, price, image_url, description, category, subcategory, product_type, variant, colors_json, sizes_json, active))
            row = cur.fetchone()
        return jsonify({"product": product_row_dict(row)}), 201
    except Exception as e:
        return jsonify({"error": f"Failed to create product: {str(e)[:180]}"}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.route("/api/products/<int:pid>", methods=["PUT"])
@login_required
def update_product(pid):
    if not validate_csrf():
        return jsonify({"error": "Invalid CSRF token"}), 403
    conn = get_connection()
    if not conn:
        return jsonify({"error": "Database unavailable. Changes cannot be saved."}), 503
    try:
        data = request.get_json(silent=True) or {}
        name = sanitize_str(data.get("name"), 200)
        price = data.get("price")
        image_url = normalize_image_url(sanitize_str(data.get("image_url"), 1000))
        description = sanitize_str(data.get("description"), 2000)
        category = sanitize_str(data.get("category"), 50) or "men"
        subcategory = sanitize_str(data.get("subcategory"), 80)
        product_type = sanitize_str(data.get("product_type"), 80)
        variant = sanitize_str(data.get("variant"), 80)
        colors = data.get("colors", [])
        sizes = data.get("sizes", [])
        active = data.get("active")

        if not name:
            return jsonify({"error": "Product name is required"}), 400
        try:
            price = int(price)
            if price < 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Valid price (NPR) is required"}), 400
        if image_url and not is_safe_image_url(image_url):
            return jsonify({"error": "Invalid image URL"}), 400

        colors_json = json.dumps(colors if isinstance(colors, list) else [])
        sizes_json = json.dumps(sizes if isinstance(sizes, list) else [])

        init_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM products WHERE id = %s", (pid,))
            exists = cur.fetchone()
            if not exists:
                # Catalog / fallback edit → insert as real row so it becomes editable in DB
                cur.execute("""
                    INSERT INTO products
                    (name, price, image_url, description, category, subcategory, product_type, variant, colors, sizes, active)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id, name, price, image_url, description, category, subcategory, product_type, variant, colors, sizes, active
                """, (name, price, image_url, description, category, subcategory, product_type, variant,
                      colors_json, sizes_json, True if active is None else bool(active)))
            else:
                cur.execute("""
                    UPDATE products SET
                        name = %s, price = %s, image_url = %s, description = %s,
                        category = %s, subcategory = %s, product_type = %s, variant = %s,
                        colors = %s, sizes = %s,
                        active = COALESCE(%s, active),
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, name, price, image_url, description, category, subcategory, product_type, variant, colors, sizes, active
                """, (name, price, image_url, description, category, subcategory, product_type, variant,
                      colors_json, sizes_json, active if active is not None else None, pid))
            row = cur.fetchone()
        return jsonify({"product": product_row_dict(row), "message": "Saved"})
    except Exception as e:
        return jsonify({"error": f"Failed to update product: {str(e)[:180]}"}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.route("/api/products/<int:pid>", methods=["DELETE"])
@login_required
def delete_product(pid):
    if not validate_csrf():
        return jsonify({"error": "Invalid CSRF token"}), 403
    conn = get_connection()
    if not conn:
        return jsonify({"error": "Database unavailable. Changes cannot be saved."}), 503
    try:
        init_schema(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM products WHERE id = %s RETURNING id", (pid,))
            if not cur.fetchone():
                return jsonify({"error": "Product not found"}), 404
        return jsonify({"ok": True})
    except Exception:
        return jsonify({"error": "Failed to delete product"}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# API: Settings (logo / favicon)
# ---------------------------------------------------------------------------

@app.route("/api/settings", methods=["GET"])
def get_settings():
    defaults = {
        "logo_url": "",
        "favicon_url": "",
        "brand_name": "Atelier Lane",
        "facebook_url": "",
        "instagram_url": "",
        "whatsapp": "",
        "source": "fallback",
    }
    conn = get_connection()
    if not conn:
        return jsonify(defaults)
    try:
        init_schema(conn)
        row = None
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                cur.execute("""
                    SELECT logo_url, favicon_url, brand_name, facebook_url, instagram_url, whatsapp
                    FROM website_settings WHERE id = 1
                """)
                row = cur.fetchone()
            except Exception:
                # Older row / partial schema — force migrate and retry
                init_schema(conn)
                cur.execute("""
                    SELECT logo_url, favicon_url,
                           COALESCE(brand_name, 'Atelier Lane') AS brand_name,
                           COALESCE(facebook_url, '') AS facebook_url,
                           COALESCE(instagram_url, '') AS instagram_url,
                           COALESCE(whatsapp, '') AS whatsapp
                    FROM website_settings WHERE id = 1
                """)
                row = cur.fetchone()
        if not row:
            defaults["source"] = "live"
            return jsonify(defaults)
        d = dict(row)
        return jsonify({
            "logo_url": d.get("logo_url") or "",
            "favicon_url": d.get("favicon_url") or "",
            "brand_name": (d.get("brand_name") or "Atelier Lane").strip() or "Atelier Lane",
            "facebook_url": d.get("facebook_url") or "",
            "instagram_url": d.get("instagram_url") or "",
            "whatsapp": d.get("whatsapp") or "",
            "source": "live",
        })
    except Exception as e:
        defaults["error"] = str(e)[:120]
        return jsonify(defaults)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.route("/api/settings", methods=["PUT"])
@login_required
def update_settings():
    if not validate_csrf():
        return jsonify({"error": "Invalid CSRF token"}), 403
    conn = get_connection()
    if not conn:
        return jsonify({"error": "Database unavailable. Changes cannot be saved."}), 503
    try:
        data = request.get_json(silent=True) or {}
        logo_url = sanitize_str(data.get("logo_url"), 500)
        favicon_url = sanitize_str(data.get("favicon_url"), 500)
        brand_name = sanitize_str(data.get("brand_name"), 120) or "Atelier Lane"
        facebook_url = sanitize_str(data.get("facebook_url"), 500)
        instagram_url = sanitize_str(data.get("instagram_url"), 500)
        whatsapp = sanitize_str(data.get("whatsapp"), 40)
        # normalize whatsapp to digits only for wa.me links
        whatsapp_digits = re.sub(r"[^0-9]", "", whatsapp)
        if logo_url and not is_safe_image_url(logo_url):
            return jsonify({"error": "Invalid logo URL"}), 400
        if favicon_url and not is_safe_image_url(favicon_url):
            return jsonify({"error": "Invalid favicon URL"}), 400
        for label, url in (("Facebook", facebook_url), ("Instagram", instagram_url)):
            if url and not (url.startswith("https://") or url.startswith("http://")):
                return jsonify({"error": f"Invalid {label} URL — use full https link"}), 400

        init_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                UPDATE website_settings SET
                    logo_url = %s, favicon_url = %s, brand_name = %s,
                    facebook_url = %s, instagram_url = %s, whatsapp = %s,
                    updated_at = NOW()
                WHERE id = 1
                RETURNING logo_url, favicon_url, brand_name, facebook_url, instagram_url, whatsapp
            """, (logo_url, favicon_url, brand_name, facebook_url, instagram_url, whatsapp_digits or whatsapp))
            row = cur.fetchone()
        return jsonify({
            "logo_url": row["logo_url"] or "",
            "favicon_url": row["favicon_url"] or "",
            "brand_name": row["brand_name"] or "Atelier Lane",
            "facebook_url": row["facebook_url"] or "",
            "instagram_url": row["instagram_url"] or "",
            "whatsapp": row["whatsapp"] or "",
        })
    except Exception as e:
        msg = str(e)
        # Column missing — try migrate then retry once
        if "brand_name" in msg or "does not exist" in msg.lower() or "facebook_url" in msg:
            try:
                init_schema(conn)
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        UPDATE website_settings SET
                            logo_url = %s, favicon_url = %s, brand_name = %s,
                            facebook_url = %s, instagram_url = %s, whatsapp = %s,
                            updated_at = NOW()
                        WHERE id = 1
                        RETURNING logo_url, favicon_url, brand_name, facebook_url, instagram_url, whatsapp
                    """, (logo_url, favicon_url, brand_name, facebook_url, instagram_url, whatsapp_digits or whatsapp))
                    row = cur.fetchone()
                return jsonify({
                    "logo_url": row["logo_url"] or "",
                    "favicon_url": row["favicon_url"] or "",
                    "brand_name": row["brand_name"] or "Atelier Lane",
                    "facebook_url": row["facebook_url"] or "",
                    "instagram_url": row["instagram_url"] or "",
                    "whatsapp": row["whatsapp"] or "",
                })
            except Exception as e2:
                return jsonify({"error": f"Failed to update settings: {str(e2)[:180]}"}), 500
        return jsonify({"error": f"Failed to update settings: {msg[:180]}"}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# API: Homepage notice
# ---------------------------------------------------------------------------

@app.route("/api/notice", methods=["GET"])
def get_notice():
    conn = get_connection()
    if not conn:
        return jsonify({"notice": None, "source": "fallback"})
    try:
        init_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT title, message, image_url, button_text, button_url,
                       notice_type, enabled, start_date, end_date
                FROM homepage_notice WHERE id = 1
            """)
            row = cur.fetchone()
        if not row:
            return jsonify({"notice": None, "source": "live"})
        # Date filtering
        today = datetime.now(NPT).date()
        if row["start_date"] and today < row["start_date"]:
            enabled = False
        elif row["end_date"] and today > row["end_date"]:
            enabled = False
        else:
            enabled = bool(row["enabled"])
        notice = {
            "title": row["title"] or "",
            "message": row["message"] or "",
            "image_url": row["image_url"] or "",
            "button_text": row["button_text"] or "",
            "button_url": row["button_url"] or "",
            "notice_type": row["notice_type"] or "banner",
            "enabled": enabled,
            "start_date": row["start_date"].isoformat() if row["start_date"] else None,
            "end_date": row["end_date"].isoformat() if row["end_date"] else None,
        }
        return jsonify({"notice": notice, "source": "live"})
    except Exception:
        return jsonify({"notice": None, "source": "fallback"})
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.route("/api/notice", methods=["PUT"])
@login_required
def update_notice():
    if not validate_csrf():
        return jsonify({"error": "Invalid CSRF token"}), 403
    conn = get_connection()
    if not conn:
        return jsonify({"error": "Database unavailable. Changes cannot be saved."}), 503
    try:
        data = request.get_json(silent=True) or {}
        title = sanitize_str(data.get("title"), 200)
        message = sanitize_str(data.get("message"), 2000)
        image_url = normalize_image_url(sanitize_str(data.get("image_url"), 1000))
        button_text = sanitize_str(data.get("button_text"), 100)
        button_url = sanitize_str(data.get("button_url"), 500)
        notice_type = sanitize_str(data.get("notice_type"), 20) or "banner"
        if notice_type not in ("banner", "modal"):
            notice_type = "banner"
        enabled = bool(data.get("enabled", False))
        start_date = data.get("start_date") or None
        end_date = data.get("end_date") or None
        if image_url and not is_safe_image_url(image_url):
            return jsonify({"error": "Invalid notice image URL"}), 400

        init_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                UPDATE homepage_notice SET
                    title = %s, message = %s, image_url = %s,
                    button_text = %s, button_url = %s, notice_type = %s,
                    enabled = %s, start_date = %s, end_date = %s,
                    updated_at = NOW()
                WHERE id = 1
                RETURNING title, message, image_url, button_text, button_url,
                          notice_type, enabled, start_date, end_date
            """, (title, message, image_url, button_text, button_url, notice_type,
                  enabled, start_date, end_date))
            row = cur.fetchone()
        notice = {
            "title": row["title"] or "",
            "message": row["message"] or "",
            "image_url": row["image_url"] or "",
            "button_text": row["button_text"] or "",
            "button_url": row["button_url"] or "",
            "notice_type": row["notice_type"],
            "enabled": bool(row["enabled"]),
            "start_date": row["start_date"].isoformat() if row["start_date"] else None,
            "end_date": row["end_date"].isoformat() if row["end_date"] else None,
        }
        return jsonify({"notice": notice})
    except Exception:
        return jsonify({"error": "Failed to update notice"}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# API: Orders
# ---------------------------------------------------------------------------

@app.route("/api/order", methods=["POST"])
def create_order():
    data = request.get_json(silent=True) or {}
    name = sanitize_str(data.get("name"), 150)
    email = sanitize_str(data.get("email"), 200)
    phone = sanitize_str(data.get("phone"), 40)
    address = sanitize_str(data.get("address"), 500)
    city = sanitize_str(data.get("city"), 100)
    notes = sanitize_str(data.get("notes"), 1000)
    items = data.get("items", [])

    if not name or not email or not phone or not address or not city:
        return jsonify({"error": "Name, email, phone, address and city are required"}), 400
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify({"error": "Invalid email address"}), 400
    if not isinstance(items, list) or len(items) == 0:
        return jsonify({"error": "Cart is empty"}), 400
    if len(items) > 50:
        return jsonify({"error": "Too many items"}), 400

    # Server-side price verification against live DB (or reject if DB down for orders)
    conn = get_connection()
    if not conn:
        return jsonify({
            "error": "Order service temporarily unavailable. Please try again later."
        }), 503

    try:
        init_schema(conn)
        verified_items = []
        total = 0
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for it in items:
                pid = it.get("id")
                qty = it.get("quantity", 1)
                try:
                    qty = int(qty)
                    if qty < 1 or qty > 20:
                        return jsonify({"error": "Invalid quantity"}), 400
                except (TypeError, ValueError):
                    return jsonify({"error": "Invalid quantity"}), 400
                size = sanitize_str(it.get("size"), 20)
                color = sanitize_str(it.get("color"), 40)
                cur.execute(
                    "SELECT id, name, price, active FROM products WHERE id = %s",
                    (pid,),
                )
                prod = cur.fetchone()
                if not prod or not prod["active"]:
                    return jsonify({"error": f"Product unavailable (id {pid})"}), 400
                line_total = prod["price"] * qty
                total += line_total
                verified_items.append({
                    "id": prod["id"],
                    "name": prod["name"],
                    "price": prod["price"],
                    "quantity": qty,
                    "size": size,
                    "color": color,
                    "subtotal": line_total,
                })

        order_ref = "ABC-" + secrets.token_hex(4).upper() + "-" + str(int(time.time()) % 10000)
        items_json = json.dumps(verified_items)

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO orders (order_ref, customer_name, customer_email, customer_phone,
                                    address, city, notes, items, total, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            """, (order_ref, name, email, phone, address, city, notes, items_json, total))

        # Send email notification
        email_sent = False
        email_error = None
        try:
            email_sent = send_order_email(order_ref, name, email, phone, address, city, notes, verified_items, total)
        except Exception as e:
            email_error = str(e)

        return jsonify({
            "ok": True,
            "order_ref": order_ref,
            "total": total,
            "email_sent": email_sent,
            "message": "Order request received. We will confirm shortly. No payment has been processed.",
        }), 201
    except Exception:
        return jsonify({"error": "Failed to process order"}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass



def _email_shell(title, body_html, brand="Atelier Lane"):
    """Branded HTML email shell."""
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        '<body style="margin:0;padding:0;background:#f4f2ee;font-family:system-ui,sans-serif;">'
        '<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f2ee;padding:24px 12px;"><tr><td align="center">'
        '<table width="100%" style="max-width:560px;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 8px 28px rgba(0,0,0,.06);">'
        '<tr><td style="background:linear-gradient(135deg,#20201E,#3a3a36);padding:22px 24px;">'
        f'<div style="color:#F5C542;font-size:13px;letter-spacing:.12em;text-transform:uppercase;">{_escape(brand)}</div>'
        f'<div style="color:#fff;font-size:22px;font-weight:600;margin-top:6px;">{_escape(title)}</div>'
        '</td></tr>'
        f'<tr><td style="padding:24px;color:#20201E;line-height:1.55;font-size:15px;">{body_html}</td></tr>'
        f'<tr><td style="padding:14px 24px 22px;color:#888;font-size:12px;border-top:1px solid #eee;">Sent by {_escape(brand)}</td></tr>'
        '</table></td></tr></table></body></html>'
    )

def send_smtp_email(subject, html_body, reply_to=None):
    """Send email via SMTP. Returns True on success."""
    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587") or 587)
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    email_from = os.environ.get("EMAIL_FROM", "").strip() or user
    shop = os.environ.get("SHOP_EMAIL", "argonbhujel1@gmail.com").strip()
    if not host or not user or not password:
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = shop
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                server.login(user, password)
                server.sendmail(email_from, [shop], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(user, password)
                server.sendmail(email_from, [shop], msg.as_string())
        return True
    except Exception as e:
        app.config["_last_smtp_error"] = str(e)[:180]
        return False


def send_order_email(order_ref, name, email, phone, address, city, notes, items, total):
    rows = ""
    for it in items:
        rows += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee;">{_escape(it['name'])}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{_escape(it.get('size',''))} / {_escape(it.get('color',''))}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{it['quantity']}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">NPR {it['price']:,}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">NPR {it['subtotal']:,}</td>
        </tr>
        """
    now = datetime.now(NPT).strftime("%Y-%m-%d %H:%M NPT")
    brand = os.environ.get("SHOP_BRAND", "Atelier Lane")
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;">
      <h2 style="color:#20201E;">New Order — { _escape(order_ref) }</h2>
      <p><strong>Time:</strong> {now}</p>
      <h3>Customer</h3>
      <p>
        Name: {_escape(name)}<br>
        Email: {_escape(email)}<br>
        Phone: {_escape(phone)}<br>
        Address: {_escape(address)}<br>
        City: {_escape(city)}
      </p>
      {"<p><strong>Notes:</strong> " + _escape(notes) + "</p>" if notes else ""}
      <h3>Items</h3>
      <table style="width:100%;border-collapse:collapse;">
        <thead>
          <tr style="background:#F7F4ED;">
            <th style="padding:8px;text-align:left;">Product</th>
            <th style="padding:8px;text-align:left;">Size/Color</th>
            <th style="padding:8px;text-align:left;">Qty</th>
            <th style="padding:8px;text-align:left;">Price</th>
            <th style="padding:8px;text-align:left;">Subtotal</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="font-size:1.2em;margin-top:16px;"><strong>Total: NPR {total:,}</strong></p>
      <p style="color:#666;font-size:0.9em;">Order request only — no payment processed. — { _escape(brand) }</p>
    </div>
    """
    return send_smtp_email(f"[{brand}] Order {order_ref} — NPR {total:,}", _email_shell(f"Order {order_ref}", html, brand), reply_to=email)


def _escape(s):
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# API: Contact
# ---------------------------------------------------------------------------


@app.route("/api/contact-developer", methods=["POST"])
def contact_developer():
    """Public form on Teams → Site developers. Emails developer inbox."""
    data = request.get_json(silent=True) or {}
    name = sanitize_str(data.get("name"), 150)
    email = sanitize_str(data.get("email"), 200)
    phone = sanitize_str(data.get("phone"), 40)
    message = sanitize_str(data.get("message"), 3000)
    if not name or not email or not message:
        return jsonify({"error": "Name, email and message are required"}), 400
    if "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"error": "Valid email required"}), 400

    brand = os.environ.get("SHOP_BRAND", "Atelier Lane")
    # Prefer DEVELOPER_EMAIL, else fixed default
    to_addr = (
        os.environ.get("DEVELOPER_EMAIL", "").strip()
        or "argonbhujel1@gmail.com"
    )
    body = f"""
      <p><strong>From:</strong> {_escape(name)} &lt;{_escape(email)}&gt;</p>
      {"<p><strong>Phone:</strong> " + _escape(phone) + "</p>" if phone else ""}
      <p><strong>Message:</strong></p>
      <p style="white-space:pre-wrap;">{_escape(message)}</p>
      <p style="color:#888;font-size:12px;margin-top:16px;">Sent from { _escape(brand) } — Teams → Contact developer</p>
    """
    # Temporarily send via SMTP to developer address
    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587") or 587)
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    email_from = os.environ.get("EMAIL_FROM", "").strip() or user
    if not host or not user or not password:
        return jsonify({"error": "Email is not configured on the server yet."}), 503
    try:
        html = _email_shell("Contact developer", body, brand)
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{brand}] Contact developer — {name}"
        msg["From"] = email_from
        msg["To"] = to_addr
        msg["Reply-To"] = email
        msg.attach(MIMEText(html, "html", "utf-8"))
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                server.login(user, password)
                server.sendmail(email_from, [to_addr], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(user, password)
                server.sendmail(email_from, [to_addr], msg.as_string())
        return jsonify({"ok": True, "message": "Message sent to the developer team."})
    except Exception as e:
        app.config["_last_smtp_error"] = str(e)[:180]
        return jsonify({"error": "Could not send email. Try again later."}), 500


@app.route("/api/contact", methods=["POST"])
def contact():
    data = request.get_json(silent=True) or {}
    name = sanitize_str(data.get("name"), 150)
    email = sanitize_str(data.get("email"), 200)
    message = sanitize_str(data.get("message"), 3000)
    if not name or not email or not message:
        return jsonify({"error": "Name, email and message are required"}), 400
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify({"error": "Invalid email"}), 400

    brand = os.environ.get("SHOP_BRAND", "Atelier Lane")
    html = f"""
        <div style="font-family:system-ui,sans-serif;">
          <h2>Contact Form — {_escape(brand)}</h2>
          <p><strong>From:</strong> {_escape(name)} &lt;{_escape(email)}&gt;</p>
          <p><strong>Message:</strong></p>
          <p style="white-space:pre-wrap;">{_escape(message)}</p>
        </div>
        """
    ok = send_smtp_email(f"[{brand}] Contact from {name}", _email_shell(f"Message from {name}", html, brand), reply_to=email)
    if ok:
        return jsonify({"ok": True, "message": "Message sent. We will reply soon."})
    return jsonify({"error": "Email service is not configured or failed. Please try again later."}), 503


# ---------------------------------------------------------------------------
# Admin: Auth pages & CSRF
# ---------------------------------------------------------------------------

@app.route("/api/csrf", methods=["GET"])
def get_csrf():
    return jsonify({"csrf_token": csrf_token()})


LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Admin Login — ABC Clothing</title>
  <style>
    :root { --bg:#F7F4ED; --fg:#20201E; --accent:#FF6545; --muted:#888; }
    * { box-sizing:border-box; margin:0; padding:0; }
    body { font-family: system-ui, -apple-system, sans-serif; background:var(--bg); color:var(--fg);
           min-height:100vh; display:flex; align-items:center; justify-content:center; padding:1rem; }
    .card { background:#fff; border-radius:16px; padding:2.5rem; width:100%; max-width:400px;
            box-shadow:0 8px 32px rgba(0,0,0,0.08); }
    h1 { font-size:1.5rem; margin-bottom:0.25rem; }
    .sub { color:var(--muted); margin-bottom:1.75rem; font-size:0.9rem; }
    label { display:block; font-size:0.85rem; font-weight:600; margin-bottom:0.35rem; }
    input { width:100%; padding:0.75rem 1rem; border:1.5px solid #ddd; border-radius:10px;
            font-size:1rem; margin-bottom:1rem; }
    input:focus { outline:none; border-color:var(--accent); }
    button { width:100%; padding:0.85rem; background:var(--accent); color:#fff; border:none;
             border-radius:10px; font-size:1rem; font-weight:600; cursor:pointer; }
    button:hover { filter:brightness(1.05); }
    .err { background:#fee; color:#c00; padding:0.75rem; border-radius:8px; margin-bottom:1rem; font-size:0.9rem; }
    .credit { text-align:center; margin-top:1.5rem; font-size:0.8rem; color:var(--muted); }
    .credit a { color:var(--accent); }
  </style>
</head>
<body>
  <div class="card">
    <h1>ABC Clothing</h1>
    <p class="sub">Admin sign in</p>
    {% if error %}<div class="err">{{ error }}</div>{% endif %}
    <form method="POST" action="/siteadmin/login/admin">
      <input type="hidden" name="csrf_token" value="{{ csrf }}">
      <label for="username">Username</label>
      <input id="username" name="username" required autocomplete="username">
      <label for="password">Password</label>
      <input id="password" name="password" type="password" required autocomplete="current-password">
      <button type="submit">Sign in</button>
    </form>
    <p class="credit">Technology by <a href="https://bamstudio.argan.com.np/" target="_blank" rel="noopener noreferrer">BAM Studio</a></p>
  </div>
</body>
</html>
"""


@app.route("/siteadmin/login/admin", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect("/siteadmin/dashboard")
    error = None
    if request.method == "POST":
        if not validate_csrf():
            error = "Invalid session. Refresh the page and try again."
        else:
            ip = request.headers.get("X-Forwarded-For", request.remote_addr or "0.0.0.0").split(",")[0].strip()
            if not check_rate_limit(ip):
                error = "Too many attempts. Try again in 15 minutes."
            else:
                username = sanitize_str(request.form.get("username"), 80)
                password = request.form.get("password") or ""
                env_user = os.environ.get("INITIAL_ADMIN_USERNAME", "").strip()
                env_pass = os.environ.get("INITIAL_ADMIN_PASSWORD", "").strip()

                # 1) Env credentials always work (primary bootstrap login)
                if env_user and env_pass and username == env_user and password == env_pass:
                    session.permanent = True
                    session["admin_logged_in"] = True
                    session["admin_username"] = username
                    session["admin_id"] = 0
                    conn = get_connection()
                    if conn:
                        try:
                            init_schema(conn)
                            ensure_admin_user(conn)
                            with conn.cursor() as cur:
                                cur.execute(
                                    "SELECT id FROM admin_users WHERE username = %s",
                                    (username,),
                                )
                                row = cur.fetchone()
                                if row:
                                    session["admin_id"] = row[0]
                            session.pop("offline_mode", None)
                        except Exception:
                            session["offline_mode"] = True
                        finally:
                            try:
                                conn.close()
                            except Exception:
                                pass
                    else:
                        session["offline_mode"] = True
                    reset_rate_limit(ip)
                    return redirect("/siteadmin/dashboard")

                # 2) DB-stored admin (other users or after password change in DB)
                conn = get_connection()
                if not conn:
                    if not env_user or not env_pass:
                        error = "Set INITIAL_ADMIN_USERNAME and INITIAL_ADMIN_PASSWORD in Vercel env."
                    else:
                        error = "Invalid username or password. Use the INITIAL_ADMIN_* credentials from Vercel."
                else:
                    try:
                        init_schema(conn)
                        ensure_admin_user(conn)
                        with conn.cursor() as cur:
                            cur.execute(
                                "SELECT id, password_hash FROM admin_users WHERE username = %s",
                                (username,),
                            )
                            row = cur.fetchone()
                        ok = False
                        if row:
                            try:
                                ok = check_password_hash(row[1], password)
                            except Exception:
                                ok = False
                        if ok:
                            session.permanent = True
                            session["admin_logged_in"] = True
                            session["admin_id"] = row[0]
                            session["admin_username"] = username
                            session.pop("offline_mode", None)
                            reset_rate_limit(ip)
                            return redirect("/siteadmin/dashboard")
                        error = "Invalid username or password."
                    except Exception as e:
                        # Fall back: if env matches we already handled above
                        error = f"Login failed ({str(e)[:80]}). Use INITIAL_ADMIN_USERNAME / INITIAL_ADMIN_PASSWORD from Vercel env."
                    finally:
                        try:
                            conn.close()
                        except Exception:
                            pass
    return render_template_string(LOGIN_HTML, error=error, csrf=csrf_token())


@app.route("/siteadmin/logout")
def admin_logout():
    session.clear()
    return redirect("/siteadmin/login/admin")


# ---------------------------------------------------------------------------
# Admin Dashboard (single-page SPA-like HTML served by Flask)
# ---------------------------------------------------------------------------

DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Admin — ABC Clothing</title>
  <style>
    :root {
      --bg: #F7F4ED; --fg: #20201E; --accent: #FF6545; --lime: #D9F36B;
      --card: #fff; --muted: #666; --border: #e5e2da; --danger: #c0392b;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--fg); min-height: 100vh; }
    header { background: var(--fg); color: #fff; padding: 1rem 1.5rem; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.75rem; }
    header h1 { font-size: 1.15rem; font-weight: 600; }
    header a { color: #fff; text-decoration: none; font-size: 0.9rem; opacity: 0.85; }
    header a:hover { opacity: 1; }
    nav { display: flex; gap: 0.5rem; background: #fff; border-bottom: 1px solid var(--border); padding: 0.5rem 1rem; flex-wrap: wrap; }
    nav button { background: transparent; border: none; padding: 0.6rem 1rem; border-radius: 8px; cursor: pointer; font-size: 0.95rem; font-weight: 500; color: var(--muted); }
    nav button.active, nav button:hover { background: var(--bg); color: var(--fg); }
    main { max-width: 960px; margin: 0 auto; padding: 1.5rem 1rem 3rem; }
    .card { background: var(--card); border-radius: 14px; padding: 1.5rem; margin-bottom: 1.25rem; box-shadow: 0 2px 12px rgba(0,0,0,0.04); }
    h2 { font-size: 1.25rem; margin-bottom: 1rem; }
    label { display: block; font-size: 0.85rem; font-weight: 600; margin-bottom: 0.3rem; margin-top: 0.85rem; }
    input, select, textarea { width: 100%; padding: 0.65rem 0.85rem; border: 1.5px solid var(--border); border-radius: 8px; font-size: 0.95rem; }
    input:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent); }
    textarea { min-height: 90px; resize: vertical; }
    .row { display: flex; gap: 1rem; flex-wrap: wrap; }
    .row > * { flex: 1; min-width: 140px; }
    .btn { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.65rem 1.1rem; border: none; border-radius: 8px; font-size: 0.95rem; font-weight: 600; cursor: pointer; }
    .btn-primary { background: var(--accent); color: #fff; }
    .btn-secondary { background: var(--fg); color: #fff; }
    .btn-ghost { background: transparent; border: 1.5px solid var(--border); color: var(--fg); }
    .btn-danger { background: var(--danger); color: #fff; }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
    table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    th, td { text-align: left; padding: 0.65rem 0.5rem; border-bottom: 1px solid var(--border); }
    th { font-weight: 600; color: var(--muted); font-size: 0.8rem; text-transform: uppercase; }
    .badge { display: inline-block; padding: 0.2rem 0.5rem; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }
    .badge-on { background: #d4edda; color: #155724; }
    .badge-off { background: #f8d7da; color: #721c24; }
    .thumb { width: 48px; height: 48px; object-fit: cover; border-radius: 6px; background: #eee; }
    .preview { max-width: 120px; max-height: 80px; object-fit: contain; border-radius: 6px; margin-top: 0.5rem; background: #f0f0f0; }
    .toast { position: fixed; bottom: 1.5rem; right: 1.5rem; background: var(--fg); color: #fff; padding: 0.85rem 1.25rem; border-radius: 10px; font-size: 0.9rem; z-index: 100; opacity: 0; transform: translateY(12px); transition: all 0.3s; pointer-events: none; }
    .toast.show { opacity: 1; transform: translateY(0); }
    .toast.err { background: var(--danger); }
    .warn { background: #fff3cd; color: #856404; padding: 0.75rem 1rem; border-radius: 8px; margin-bottom: 1rem; font-size: 0.9rem; }
    .actions { display: flex; gap: 0.4rem; flex-wrap: wrap; }
    .hidden { display: none !important; }
    .credit { text-align: center; padding: 1.5rem; font-size: 0.8rem; color: var(--muted); }
    .credit a { color: var(--accent); }
    .link-btn { background: none; border: none; color: var(--accent); cursor: pointer; font-size: 0.85rem; text-decoration: underline; }
  </style>
</head>
<body>
  <header>
    <h1>ABC Clothing Admin</h1>
    <div>
      <span style="opacity:0.7;margin-right:1rem;font-size:0.9rem;">{{ username }}</span>
      <a href="/siteadmin/logout">Logout</a>
    </div>
  </header>
  <nav>
    <button type="button" data-tab="add" class="active">Add</button>
    <button type="button" data-tab="products">Products</button>
    <button type="button" data-tab="notice">Homepage Notice</button>
    <button type="button" data-tab="branding">Website Branding</button>
    <button type="button" data-tab="teams">Teams</button>
    <button type="button" data-tab="data">Neon data</button>
  </nav>
  <main>
    <div id="db-warn" class="warn hidden">Database is currently unavailable. Changes cannot be saved. Your form inputs are preserved.</div>

    <!-- ADD PRODUCT -->
    <section id="tab-add">
      <div class="card">
        <h2 id="form-title">Add product</h2>
        <p style="font-size:0.85rem;color:var(--muted);margin-bottom:1rem">Create a new item. To change an existing one, use the <strong>Products</strong> tab.</p>
        <form id="product-form">
          <input type="hidden" id="p-id">
          <label>Name *</label>
          <input id="p-name" required maxlength="200">
          <div class="row">
            <div>
              <label>Price (NPR) *</label>
              <input id="p-price" type="number" min="0" step="1" required>
            </div>
            <div>
              <label>Category</label>
              <label>Main category</label>
              <select id="p-category">
                <option value="men">Men's Wear</option>
                <option value="women">Women's Wear</option>
                <option value="kids">Kids' Wear</option>
                <option value="unisex">Unisex Wear</option>
                <option value="streetwear">Streetwear</option>
              </select>
              <label style="margin-top:0.75rem;display:block;">Sub category</label>
              <select id="p-subcategory"><option value="">—</option></select>
              <label style="margin-top:0.75rem;display:block;">Type</label>
              <select id="p-product-type"><option value="">—</option></select>
              <label style="margin-top:0.75rem;display:block;">Variant</label>
              <select id="p-variant"><option value="">—</option></select>
              <p style="font-size:0.8rem;color:var(--muted);margin-top:0.35rem;">Path example: Men's Wear → Bottom Wear → Jeans → Baggy</p>
            </div>
            <div>
              <label>Active</label>
              <select id="p-active">
                <option value="true">Yes — visible in store</option>
                <option value="false">No — hidden</option>
              </select>
            </div>
          </div>
          <label>Description</label>
          <textarea id="p-desc" maxlength="2000"></textarea>
          <label>Product Image URL (ImgBB direct link)</label>
          <input id="p-image" placeholder="https://i.ibb.co/....">
          <p style="font-size:0.8rem;color:var(--muted);margin-top:0.3rem;">
            Upload at <a href="https://imgbb.com/" target="_blank" rel="noopener noreferrer">imgbb.com</a> →
            copy <strong>Direct link</strong> (must start with <code>https://i.ibb.co/...</code>, not the page link).
            <button type="button" class="link-btn" id="preview-img-btn">Preview</button>
          </p>
          <img id="p-preview" class="preview hidden" alt="Preview">
          <label>Colors (comma-separated)</label>
          <input id="p-colors" placeholder="Black, White, Navy">
          <label>Sizes (comma-separated)</label>
          <input id="p-sizes" placeholder="S, M, L, XL">
          <div style="margin-top:1.25rem;display:flex;gap:0.5rem;flex-wrap:wrap;">
            <button type="submit" class="btn btn-primary" id="p-save">Save</button>
            <button type="button" class="btn btn-ghost hidden" id="p-cancel">Cancel Edit</button>
          </div>
        </form>
      </div>
    </section>

    <!-- NOTICE -->
    <!-- BROWSE / EDIT PRODUCTS -->
    <section id="tab-products" class="hidden">
      <div class="card">
        <h2>Products</h2>
        <p style="font-size:0.85rem;color:var(--muted);margin-bottom:1rem">
          Choose a class → then a type (jeans, t-shirt, …) → then edit a product (including catalog items & images).
        </p>
        <button type="button" class="btn btn-ghost" id="btn-seed-catalog" style="margin-bottom:1rem">Import hardcoded catalog into DB (if empty)</button>
        <div id="product-drill" style="margin-bottom:1rem"></div>
        <div id="product-list"></div>
      </div>
    </section>

    <section id="tab-notice" class="hidden">
      <div class="card">
        <h2>Homepage Notice</h2>
        <form id="notice-form">
          <label>Title</label>
          <input id="n-title" maxlength="200">
          <label>Message</label>
          <textarea id="n-message" maxlength="2000"></textarea>
          <label>Image URL (optional)</label>
          <input id="n-image" placeholder="https://i.ibb.co/....">
          <img id="n-preview" class="preview hidden" alt="Notice preview">
          <div class="row">
            <div>
              <label>Button Text</label>
              <input id="n-btn-text" maxlength="100">
            </div>
            <div>
              <label>Button URL</label>
              <input id="n-btn-url" maxlength="500">
            </div>
          </div>
          <div class="row">
            <div>
              <label>Type</label>
              <select id="n-type">
                <option value="banner">Top announcement banner</option>
                <option value="modal">Modal popup</option>
              </select>
            </div>
            <div>
              <label>Enabled</label>
              <select id="n-enabled">
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            </div>
          </div>
          <div class="row">
            <div>
              <label>Start Date (optional)</label>
              <input id="n-start" type="date">
            </div>
            <div>
              <label>End Date (optional)</label>
              <input id="n-end" type="date">
            </div>
          </div>
          <div style="margin-top:1.25rem;">
            <button type="submit" class="btn btn-primary">Save Notice</button>
          </div>
        </form>
      </div>
    </section>

    <!-- BRANDING -->
    <section id="tab-branding" class="hidden">
      <div class="card">
        <h2>Website Branding &amp; Socials</h2>
        <form id="branding-form">
          <label>Brand / Store Name</label>
          <input id="b-brand" placeholder="Atelier Lane" maxlength="120">
          <p style="font-size:0.8rem;color:var(--muted);">Changes site title, logo text, footer and all public “ABC Clothing” labels.</p>

          <label>Logo URL (ImgBB direct link)</label>
          <input id="b-logo" placeholder="https://i.ibb.co/....">
          <p style="font-size:0.8rem;color:var(--muted);">Leave empty to use text brand name.</p>
          <img id="b-logo-preview" class="preview hidden" alt="Logo preview">

          <label>Favicon URL</label>
          <input id="b-favicon" placeholder="https://i.ibb.co/....">
          <img id="b-favicon-preview" class="preview hidden" alt="Favicon preview" style="max-width:48px;max-height:48px;">

          <hr style="margin:1.5rem 0;border:none;border-top:1px solid var(--border);">
          <h3 style="font-size:1rem;margin-bottom:0.5rem;">Social &amp; Contact</h3>
          <p style="font-size:0.8rem;color:var(--muted);margin-bottom:0.75rem;">Instagram appears as a floating button on the right; WhatsApp on the left.</p>

          <label>Instagram profile or DM URL</label>
          <input id="b-instagram" placeholder="https://instagram.com/yourpage or https://ig.me/m/yourpage">
          <label>WhatsApp number (with country code, e.g. 97798xxxxxxx)</label>
          <input id="b-whatsapp" placeholder="97798xxxxxxxx">
          <label>Facebook page URL</label>
          <input id="b-facebook" placeholder="https://facebook.com/yourpage">

          <div style="margin-top:1.25rem;display:flex;gap:0.5rem;flex-wrap:wrap;">
            <button type="submit" class="btn btn-primary">Save Branding</button>
            <button type="button" class="btn btn-ghost" id="b-clear">Clear logo / favicon</button>
          </div>
        </form>
      </div>
    </section>

    
    <section id="tab-teams" class="hidden">
      <div class="card">
        <h2>Site developer team</h2>
        <p style="font-size:0.85rem;color:var(--muted)">Names &amp; roles are fixed. You can change photo URL and enable/disable only.</p>
        <div id="dev-team-list"></div>
      </div>
      <div class="card" style="margin-top:1rem">
        <h2>Owner team</h2>
        <p style="font-size:0.85rem;color:var(--muted)">Fully editable — add, edit, enable/disable, delete.</p>
        <div id="owner-team-list"></div>
        <hr style="margin:1rem 0;border:none;border-top:1px solid var(--border)">
        <h3 style="font-size:1rem">Add owner</h3>
        <div class="form-group"><label>Name</label><input id="own-name" maxlength="150"></div>
        <div class="form-group"><label>Role</label><input id="own-role" maxlength="200"></div>
        <div class="form-group"><label>Bio</label><textarea id="own-bio" rows="2" maxlength="1000"></textarea></div>
        <div class="form-group"><label>Photo URL (ImgBB)</label><input id="own-photo" maxlength="500"></div>
        <button type="button" class="btn btn-primary" id="btn-add-owner">Add owner</button>
      </div>
    </section>

    <section id="tab-data" class="hidden">
      <div class="card">
        <h2>Neon database — move your data</h2>
        <p style="font-size:0.9rem;color:var(--muted);margin-bottom:1rem;">
          When the <strong>old</strong> Neon project hits compute limits, create a <strong>new</strong> Neon project,
          put the <em>new</em> URL in <code>DATABASE_URL</code> and the <em>old</em> URL in <code>DATABASE_URL_BACKUP</code> (Vercel env), then redeploy.
          Use the tools below to copy products &amp; settings from old → new.
        </p>
        <div id="db-status-box" class="warn" style="background:#eef6ff;color:#1a3a5c;">Checking databases…</div>
        <div style="margin-top:1.25rem;display:flex;flex-wrap:wrap;gap:0.5rem;">
          <button type="button" class="btn btn-primary" id="btn-sync-backup">Copy old Neon → new Neon</button>
          <button type="button" class="btn btn-secondary" id="btn-export-active">Download JSON (active DB)</button>
          <button type="button" class="btn btn-ghost" id="btn-export-backup">Download JSON (old / backup)</button>
          <button type="button" class="btn btn-ghost" id="btn-refresh-db">Refresh status</button>
        </div>
        <hr style="margin:1.5rem 0;border:none;border-top:1px solid var(--border);">
        <h3 style="font-size:1rem;margin-bottom:0.5rem;">Import JSON into active DB</h3>
        <p style="font-size:0.85rem;color:var(--muted);">Paste an export file if you downloaded it earlier.</p>
        <textarea id="import-json" placeholder='{"products":[...],"settings":{...},"notice":{...}}' style="min-height:120px;font-family:monospace;font-size:0.8rem;"></textarea>
        <label style="margin-top:0.75rem;display:flex;align-items:center;gap:0.5rem;font-weight:500;">
          <input type="checkbox" id="import-replace" checked> Replace existing products (recommended when restoring)
        </label>
        <div style="margin-top:0.75rem;">
          <button type="button" class="btn btn-primary" id="btn-import">Import into active DB</button>
        </div>
      </div>
    </section>
  </main>
  <p class="credit">Technology by <a href="https://bamstudio.argan.com.np/" target="_blank" rel="noopener noreferrer">BAM Studio</a></p>
  <div id="toast" class="toast"></div>

  <script>
    const CSRF = "{{ csrf }}";
    let products = [];
    let dbOk = true;

    function toast(msg, isErr) {
      const t = document.getElementById("toast");
      t.textContent = msg;
      t.className = "toast show" + (isErr ? " err" : "");
      setTimeout(() => t.classList.remove("show"), 3200);
    }

    async function api(path, opts = {}) {
      const headers = { "Content-Type": "application/json", "X-CSRF-Token": CSRF };
      const res = await fetch(path, { ...opts, headers: { ...headers, ...(opts.headers || {}) }, credentials: "same-origin" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Request failed");
      return data;
    }

    // Tabs
    document.querySelectorAll("nav button").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("nav button").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        document.querySelectorAll("main > section").forEach(s => s.classList.add("hidden"));
        const panel = document.getElementById("tab-" + btn.dataset.tab);
        if (panel) panel.classList.remove("hidden");
      });
    });

    // Health / DB status
    async function checkDb() {
      try {
        const h = await fetch("/api/health").then(r => r.json());
        dbOk = h.database === "connected";
      } catch {
        dbOk = false;
      }
      document.getElementById("db-warn").classList.toggle("hidden", dbOk);
    }

    // Products
    async function loadProducts() {
      try {
        let data = await api("/api/products");
        products = data.products || [];
        if (!products.length || data.source === "fallback") {
          try {
            const seed = await api("/api/admin/seed-catalog", { method: "POST", body: JSON.stringify({}) });
            if (seed.imported) {
              toast(seed.message || ("Imported " + seed.imported + " products"));
              data = await api("/api/products");
              products = data.products || [];
            } else if (data.message) {
              toast(data.message, false);
            }
          } catch (e2) {
            if (!products.length) toast(e2.message || "Could not import catalog", true);
          }
        }
        if (!products.length) toast("No products found. Click Import catalog.", true);
        else toast(products.length + " products loaded (" + (data.source || "live") + ")", false);
        renderProducts();
      } catch (e) {
        toast(e.message, true);
      }
    }

    // Drill state for Products tab
    let drillMain = null;
    let drillType = null;

    const MAIN_LABELS = {
      men: "Men's Wear",
      women: "Women's Wear",
      kids: "Kids' Wear",
      unisex: "Unisex Wear",
      streetwear: "Streetwear",
    };

    function renderProducts() {
      const el = document.getElementById("product-list");
      const drill = document.getElementById("product-drill");
      if (!el) return;
      if (!products.length) {
        if (drill) drill.innerHTML = "";
        el.innerHTML = "<p style='color:var(--muted)'>No products yet. Use the <strong>Add</strong> tab to create one.</p>";
        return;
      }

      // Step 1: main classes
      if (!drillMain) {
        if (drill) drill.innerHTML = `<div style="font-size:0.9rem;margin-bottom:0.5rem;color:var(--muted)">Step 1 — Which class?</div>`;
        const counts = {};
        products.forEach(p => {
          const m = (p.category || "other").toLowerCase();
          counts[m] = (counts[m] || 0) + 1;
        });
        el.innerHTML = `<div class="chooser-grid" style="grid-template-columns:repeat(auto-fill,minmax(140px,1fr))">
          ${Object.keys(counts).sort().map(m => `
            <button type="button" class="chooser-card" style="cursor:pointer;border:1px solid var(--border);background:var(--color-surface)" data-drill-main="${m}">
              <strong>${esc(MAIN_LABELS[m] || m)}</strong>
              <span>${counts[m]} products</span>
            </button>`).join("")}
        </div>`;
        el.querySelectorAll("[data-drill-main]").forEach(btn => {
          btn.addEventListener("click", () => {
            drillMain = btn.getAttribute("data-drill-main");
            drillType = null;
            renderProducts();
          });
        });
        return;
      }

      const mainProducts = products.filter(p => (p.category || "").toLowerCase() === drillMain);

      // Step 2: types inside class
      if (!drillType) {
        if (drill) {
          drill.innerHTML = `
            <button type="button" class="btn btn-ghost" style="margin-bottom:0.75rem" id="drill-back-main">← All classes</button>
            <div style="font-size:0.9rem;margin-bottom:0.5rem;color:var(--muted)">Step 2 — ${esc(MAIN_LABELS[drillMain] || drillMain)} — which type?</div>`;
          document.getElementById("drill-back-main")?.addEventListener("click", () => {
            drillMain = null; drillType = null; renderProducts();
          });
        }
        const typeCounts = {};
        mainProducts.forEach(p => {
          const t = p.product_type || p.subcategory || "general";
          const label = (p.product_type || p.subcategory || "General").replace(/-/g, " ");
          if (!typeCounts[t]) typeCounts[t] = { label, n: 0 };
          typeCounts[t].n++;
        });
        el.innerHTML = `<div class="chooser-grid" style="grid-template-columns:repeat(auto-fill,minmax(140px,1fr))">
          ${Object.keys(typeCounts).sort().map(t => `
            <button type="button" class="chooser-card" style="cursor:pointer;border:1px solid var(--border);background:var(--color-surface)" data-drill-type="${t}">
              <strong style="text-transform:capitalize">${esc(typeCounts[t].label)}</strong>
              <span>${typeCounts[t].n} products</span>
            </button>`).join("")}
        </div>`;
        el.querySelectorAll("[data-drill-type]").forEach(btn => {
          btn.addEventListener("click", () => {
            drillType = btn.getAttribute("data-drill-type");
            renderProducts();
          });
        });
        return;
      }

      // Step 3: product list for type
      const list = mainProducts.filter(p =>
        (p.product_type || p.subcategory || "general") === drillType
      );
      if (drill) {
        drill.innerHTML = `
          <button type="button" class="btn btn-ghost" style="margin-bottom:0.5rem" id="drill-back-type">← ${esc(MAIN_LABELS[drillMain] || drillMain)} types</button>
          <div style="font-size:0.9rem;margin-bottom:0.75rem;color:var(--muted)">
            Step 3 — edit products in <strong>${esc(drillType.replace(/-/g," "))}</strong>
          </div>`;
        document.getElementById("drill-back-type")?.addEventListener("click", () => {
          drillType = null; renderProducts();
        });
      }
      if (!list.length) {
        el.innerHTML = "<p style='color:var(--muted)'>No products in this type.</p>";
        return;
      }
      el.innerHTML = `<table style="width:100%">
        <thead><tr><th></th><th>Product name</th><th>Price</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>
        ${list.map(p => `
          <tr>
            <td><img class="thumb" src="${p.image_url || '/assets/fallback-product.svg'}" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src='/assets/fallback-product.svg'" alt=""></td>
            <td>
              <strong>${esc(p.name)}</strong>
              <div style="font-size:0.75rem;color:var(--muted)">${esc(p.category_path || "")}</div>
            </td>
            <td>NPR ${Number(p.price).toLocaleString()}</td>
            <td><span class="badge ${p.active ? 'badge-on' : 'badge-off'}">${p.active ? 'Active' : 'Hidden'}</span></td>
            <td class="actions" style="white-space:nowrap">
              <button type="button" class="btn btn-primary" style="padding:0.35rem 0.65rem;font-size:0.8rem" onclick="editProduct(${p.id})">Edit</button>
              <button type="button" class="btn btn-ghost" style="padding:0.35rem 0.65rem;font-size:0.8rem" onclick="toggleProduct(${p.id})">${p.active ? 'Disable' : 'Enable'}</button>
              <button type="button" class="btn btn-danger" style="padding:0.35rem 0.65rem;font-size:0.8rem" onclick="deleteProduct(${p.id})">Delete</button>
            </td>
          </tr>`).join("")}
        </tbody>
      </table>`;
    }

    window.toggleProduct = async function(id) {
      const p = products.find(x => x.id === id);
      if (!p) return;
      try {
        await api("/api/products/" + id, {
          method: "PUT",
          body: JSON.stringify({
            name: p.name, price: p.price, image_url: p.image_url, description: p.description,
            category: p.category, subcategory: p.subcategory || "", product_type: p.product_type || "",
            variant: p.variant || "", colors: p.colors || [], sizes: p.sizes || [], active: !p.active
          })
        });
        toast(p.active ? "Disabled" : "Enabled");
        loadProducts();
      } catch (e) { toast(e.message, true); }
    }

    function esc(s) {
      const d = document.createElement("div");
      d.textContent = s || "";
      return d.innerHTML;
    }

    window.editProduct = function(id) {
      const p = products.find(x => x.id === id);
      if (!p) return;
      document.getElementById("p-id").value = p.id;
      document.getElementById("p-name").value = p.name;
      document.getElementById("p-price").value = p.price;
      document.getElementById("p-category").value = p.category || "men";
      onMainCat();
      document.getElementById("p-subcategory").value = p.subcategory || "";
      onSubCat();
      document.getElementById("p-product-type").value = p.product_type || "";
      onTypeCat();
      document.getElementById("p-variant").value = p.variant || "";
      document.getElementById("p-active").value = p.active ? "true" : "false";
      document.getElementById("p-desc").value = p.description || "";
      document.getElementById("p-image").value = p.image_url || "";
      document.getElementById("p-colors").value = (p.colors || []).join(", ");
      document.getElementById("p-sizes").value = (p.sizes || []).join(", ");
      document.getElementById("form-title").textContent = "Edit Product #" + p.id;
      document.getElementById("p-cancel").classList.remove("hidden");
      previewImage("p-image", "p-preview");
      document.querySelectorAll("nav button").forEach(b => {
        b.classList.toggle("active", b.dataset.tab === "add");
      });
      document.querySelectorAll("main > section").forEach(s => {
        s.classList.toggle("hidden", s.id !== "tab-add");
      });
      const ft = document.getElementById("form-title");
      if (ft) ft.textContent = "Edit product";
      const cancel = document.getElementById("p-cancel");
      if (cancel) cancel.classList.remove("hidden");
      window.scrollTo({ top: 0, behavior: "smooth" });
    };

    window.deleteProduct = async function(id) {
      if (!confirm("Delete this product permanently?")) return;
      try {
        await api("/api/products/" + id, { method: "DELETE" });
        toast("Product deleted");
        loadProducts();
      } catch (e) {
        toast(e.message, true);
      }
    };

    document.getElementById("p-cancel").addEventListener("click", () => {
      document.getElementById("product-form").reset();
        const ft2 = document.getElementById("form-title");
        if (ft2) ft2.textContent = "Add product";
      document.getElementById("p-id").value = "";
      document.getElementById("form-title").textContent = "Add product";
      document.getElementById("p-cancel").classList.add("hidden");
      document.getElementById("p-preview").classList.add("hidden");
    });

    function previewImage(inputId, imgId) {
      const input = document.getElementById(inputId);
      const img = document.getElementById(imgId);
      if (!input || !img) return;
      let url = (input.value || "").trim();
      if (!url) { img.classList.add("hidden"); img.removeAttribute("src"); return; }
      if (url.startsWith("//")) url = "https:" + url;
      img.onload = function(){ img.classList.remove("hidden"); };
      img.onerror = function(){
        img.classList.add("hidden");
        toast("Image link could not load. Use a direct image URL (e.g. https://i.ibb.co/.../file.jpg)", true);
      };
      img.src = url;
    }

    document.getElementById("preview-img-btn")?.addEventListener("click", () => previewImage("p-image", "p-preview"));
    document.getElementById("p-image")?.addEventListener("blur", () => previewImage("p-image", "p-preview"));

    document.getElementById("product-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const id = document.getElementById("p-id").value;
      const body = {
        name: document.getElementById("p-name").value.trim(),
        price: parseInt(document.getElementById("p-price").value, 10),
        category: document.getElementById("p-category").value || "men",
        subcategory: document.getElementById("p-subcategory").value || "",
        product_type: document.getElementById("p-product-type").value || "",
        variant: document.getElementById("p-variant").value || "",
        active: document.getElementById("p-active").value === "true",
        description: document.getElementById("p-desc").value.trim(),
        image_url: document.getElementById("p-image").value.trim(),
        colors: document.getElementById("p-colors").value.split(",").map(s => s.trim()).filter(Boolean),
        sizes: document.getElementById("p-sizes").value.split(",").map(s => s.trim()).filter(Boolean),
      };
      try {
        if (id) {
          await api("/api/products/" + id, { method: "PUT", body: JSON.stringify(body) });
          toast("Product updated");
        } else {
          await api("/api/products", { method: "POST", body: JSON.stringify(body) });
          toast("Product created");
        }
        document.getElementById("product-form").reset();
        const ft2 = document.getElementById("form-title");
        if (ft2) ft2.textContent = "Add product";
        document.getElementById("p-id").value = "";
        document.getElementById("form-title").textContent = "Add product";
        document.getElementById("p-cancel").classList.add("hidden");
        document.getElementById("p-preview").classList.add("hidden");
        loadProducts();
      } catch (err) {
        toast(err.message, true);
      }
    });

    // Notice
    async function loadNotice() {
      try {
        const data = await api("/api/notice");
        const n = data.notice || {};
        document.getElementById("n-title").value = n.title || "";
        document.getElementById("n-message").value = n.message || "";
        document.getElementById("n-image").value = n.image_url || "";
        document.getElementById("n-btn-text").value = n.button_text || "";
        document.getElementById("n-btn-url").value = n.button_url || "";
        document.getElementById("n-type").value = n.notice_type || "banner";
        document.getElementById("n-enabled").value = n.enabled ? "true" : "false";
        document.getElementById("n-start").value = n.start_date || "";
        document.getElementById("n-end").value = n.end_date || "";
        if (n.image_url) previewImage("n-image", "n-preview");
      } catch (e) { /* ignore */ }
    }

    document.getElementById("n-image").addEventListener("blur", () => previewImage("n-image", "n-preview"));

    document.getElementById("notice-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = {
        title: document.getElementById("n-title").value.trim(),
        message: document.getElementById("n-message").value.trim(),
        image_url: document.getElementById("n-image").value.trim(),
        button_text: document.getElementById("n-btn-text").value.trim(),
        button_url: document.getElementById("n-btn-url").value.trim(),
        notice_type: document.getElementById("n-type").value,
        enabled: document.getElementById("n-enabled").value === "true",
        start_date: document.getElementById("n-start").value || null,
        end_date: document.getElementById("n-end").value || null,
      };
      try {
        await api("/api/notice", { method: "PUT", body: JSON.stringify(body) });
        toast("Notice saved");
      } catch (err) {
        toast(err.message, true);
      }
    });

    // Branding
    async function loadBranding() {
      try {
        const data = await api("/api/settings");
        document.getElementById("b-brand").value = data.brand_name || "Atelier Lane";
        document.getElementById("b-logo").value = data.logo_url || "";
        document.getElementById("b-favicon").value = data.favicon_url || "";
        document.getElementById("b-instagram").value = data.instagram_url || "";
        document.getElementById("b-whatsapp").value = data.whatsapp || "";
        document.getElementById("b-facebook").value = data.facebook_url || "";
        if (data.logo_url) previewImage("b-logo", "b-logo-preview");
        if (data.favicon_url) previewImage("b-favicon", "b-favicon-preview");
      } catch (e) { /* ignore */ }
    }

    document.getElementById("b-logo").addEventListener("blur", () => previewImage("b-logo", "b-logo-preview"));
    document.getElementById("b-favicon").addEventListener("blur", () => previewImage("b-favicon", "b-favicon-preview"));

    document.getElementById("branding-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = {
        brand_name: document.getElementById("b-brand").value.trim() || "Atelier Lane",
        logo_url: document.getElementById("b-logo").value.trim(),
        favicon_url: document.getElementById("b-favicon").value.trim(),
        instagram_url: document.getElementById("b-instagram").value.trim(),
        whatsapp: document.getElementById("b-whatsapp").value.trim(),
        facebook_url: document.getElementById("b-facebook").value.trim(),
      };
      try {
        await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
        toast("Branding & socials saved");
      } catch (err) {
        toast(err.message, true);
      }
    });

    document.getElementById("b-clear").addEventListener("click", async () => {
      document.getElementById("b-logo").value = "";
      document.getElementById("b-favicon").value = "";
      document.getElementById("b-logo-preview").classList.add("hidden");
      document.getElementById("b-favicon-preview").classList.add("hidden");
      try {
        const body = {
          brand_name: document.getElementById("b-brand").value.trim() || "Atelier Lane",
          logo_url: "",
          favicon_url: "",
          instagram_url: document.getElementById("b-instagram").value.trim(),
          whatsapp: document.getElementById("b-whatsapp").value.trim(),
          facebook_url: document.getElementById("b-facebook").value.trim(),
        };
        await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
        toast("Logo / favicon cleared");
      } catch (err) {
        toast(err.message, true);
      }
    });


    // Category cascade
    let CAT_TREE = {};
    async function loadCatTree() {
      try {
        const r = await fetch("/api/categories");
        CAT_TREE = await r.json();
      } catch (e) { CAT_TREE = {}; }
      fillMainAlready();
      document.getElementById("p-category")?.addEventListener("change", onMainCat);
      document.getElementById("p-subcategory")?.addEventListener("change", onSubCat);
      document.getElementById("p-product-type")?.addEventListener("change", onTypeCat);
    }
    function fillMainAlready(){ onMainCat(); }
    function onMainCat() {
      const main = document.getElementById("p-category").value;
      const subSel = document.getElementById("p-subcategory");
      const typeSel = document.getElementById("p-product-type");
      const varSel = document.getElementById("p-variant");
      subSel.innerHTML = '<option value="">—</option>';
      typeSel.innerHTML = '<option value="">—</option>';
      varSel.innerHTML = '<option value="">—</option>';
      const subs = (CAT_TREE[main] || {}).subs || {};
      Object.keys(subs).forEach(k => {
        const o = document.createElement("option");
        o.value = k; o.textContent = subs[k].label || k;
        subSel.appendChild(o);
      });
    }
    function onSubCat() {
      const main = document.getElementById("p-category").value;
      const sub = document.getElementById("p-subcategory").value;
      const typeSel = document.getElementById("p-product-type");
      const varSel = document.getElementById("p-variant");
      typeSel.innerHTML = '<option value="">—</option>';
      varSel.innerHTML = '<option value="">—</option>';
      const items = (((CAT_TREE[main] || {}).subs || {})[sub] || {}).items || {};
      Object.keys(items).forEach(k => {
        const o = document.createElement("option");
        o.value = k; o.textContent = k.replace(/-/g," ").replace(/\b\w/g, c => c.toUpperCase());
        typeSel.appendChild(o);
      });
    }
    function onTypeCat() {
      const main = document.getElementById("p-category").value;
      const sub = document.getElementById("p-subcategory").value;
      const ptype = document.getElementById("p-product-type").value;
      const varSel = document.getElementById("p-variant");
      varSel.innerHTML = '<option value="">—</option>';
      const variants = ((((CAT_TREE[main] || {}).subs || {})[sub] || {}).items || {})[ptype] || [];
      variants.forEach(v => {
        const o = document.createElement("option");
        o.value = v; o.textContent = v;
        varSel.appendChild(o);
      });
    }
    loadCatTree();



    async function loadTeamAdmin() {
      try {
        const data = await api("/api/admin/team");
        const devEl = document.getElementById("dev-team-list");
        const ownEl = document.getElementById("owner-team-list");
        if (devEl) {
          devEl.innerHTML = (data.developers || []).map(m => `
            <div class="admin-class-block" style="margin-top:0.75rem">
              <div class="admin-class-head">${esc(m.name)} <span style="font-weight:400;color:var(--muted)">${esc(m.role)}</span></div>
              <div style="padding:0.75rem 1rem;display:grid;gap:0.5rem">
                <label style="font-size:0.85rem">Photo URL</label>
                <input data-dev-photo="${m.id}" value="${esc(m.photo_url || "")}" placeholder="https://i.ibb.co/...">
                <label style="font-size:0.85rem;display:flex;align-items:center;gap:0.4rem">
                  <input type="checkbox" data-dev-en="${m.id}" ${m.enabled ? "checked" : ""}> Enabled on site
                </label>
                <button type="button" class="btn btn-sm btn-primary" data-dev-save="${m.id}">Save</button>
              </div>
            </div>`).join("") || "<p>No developers</p>";
          devEl.querySelectorAll("[data-dev-save]").forEach(btn => {
            btn.addEventListener("click", async () => {
              const id = btn.getAttribute("data-dev-save");
              const photo = devEl.querySelector(`[data-dev-photo="${id}"]`).value.trim();
              const enabled = devEl.querySelector(`[data-dev-en="${id}"]`).checked;
              try {
                const res = await api("/api/admin/team/" + id, { method: "PUT", body: JSON.stringify({ photo_url: photo, enabled }) });
                toast(res.message || "Developer photo saved");
                loadTeamAdmin();
              } catch (e) { toast(e.message, true); }
            });
          });
        }
        if (ownEl) {
          ownEl.innerHTML = (data.owners || []).map(m => `
            <div class="admin-class-block" style="margin-top:0.75rem">
              <div class="admin-class-head">${esc(m.name)}
                <span>
                  <button type="button" class="btn btn-sm btn-ghost" data-own-toggle="${m.id}" data-en="${m.enabled}">${m.enabled ? "Disable" : "Enable"}</button>
                  <button type="button" class="btn btn-sm btn-ghost" data-own-del="${m.id}" style="color:var(--color-danger)">Delete</button>
                </span>
              </div>
              <div style="padding:0.75rem 1rem;display:grid;gap:0.5rem">
                <input data-own-name="${m.id}" value="${esc(m.name)}" placeholder="Name">
                <input data-own-role="${m.id}" value="${esc(m.role || "")}" placeholder="Role">
                <textarea data-own-bio="${m.id}" rows="2" placeholder="Bio">${esc(m.bio || "")}</textarea>
                <input data-own-photo="${m.id}" value="${esc(m.photo_url || "")}" placeholder="Photo URL">
                <button type="button" class="btn btn-sm btn-primary" data-own-save="${m.id}">Save</button>
              </div>
            </div>`).join("") || "<p style=\"color:var(--muted)\">No owners yet — add below.</p>";
          ownEl.querySelectorAll("[data-own-save]").forEach(btn => {
            btn.addEventListener("click", async () => {
              const id = btn.getAttribute("data-own-save");
              try {
                await api("/api/admin/team/" + id, { method: "PUT", body: JSON.stringify({
                  name: ownEl.querySelector(`[data-own-name="${id}"]`).value.trim(),
                  role: ownEl.querySelector(`[data-own-role="${id}"]`).value.trim(),
                  bio: ownEl.querySelector(`[data-own-bio="${id}"]`).value.trim(),
                  photo_url: ownEl.querySelector(`[data-own-photo="${id}"]`).value.trim(),
                })});
                toast("Owner saved"); loadTeamAdmin();
              } catch (e) { toast(e.message, true); }
            });
          });
          ownEl.querySelectorAll("[data-own-toggle]").forEach(btn => {
            btn.addEventListener("click", async () => {
              const id = btn.getAttribute("data-own-toggle");
              const en = btn.getAttribute("data-en") === "true";
              try {
                await api("/api/admin/team/" + id, { method: "PUT", body: JSON.stringify({ enabled: !en }) });
                loadTeamAdmin();
              } catch (e) { toast(e.message, true); }
            });
          });
          ownEl.querySelectorAll("[data-own-del]").forEach(btn => {
            btn.addEventListener("click", async () => {
              if (!confirm("Delete this owner?")) return;
              try {
                await api("/api/admin/team/" + btn.getAttribute("data-own-del"), { method: "DELETE" });
                loadTeamAdmin();
              } catch (e) { toast(e.message, true); }
            });
          });
        }
      } catch (e) {
        toast(e.message || "Team load failed", true);
      }
    }
    document.getElementById("btn-add-owner")?.addEventListener("click", async () => {
      try {
        await api("/api/admin/team", { method: "POST", body: JSON.stringify({
          team_type: "owner",
          name: document.getElementById("own-name").value.trim(),
          role: document.getElementById("own-role").value.trim(),
          bio: document.getElementById("own-bio").value.trim(),
          photo_url: document.getElementById("own-photo").value.trim(),
          enabled: true,
        })});
        toast("Owner added");
        ["own-name","own-role","own-bio","own-photo"].forEach(id => document.getElementById(id).value = "");
        loadTeamAdmin();
      } catch (e) { toast(e.message, true); }
    });
    document.querySelectorAll("nav button").forEach(btn => {
      btn.addEventListener("click", () => {
        if (btn.dataset.tab === "teams") loadTeamAdmin();
        if (btn.dataset.tab === "products") { drillMain = null; drillType = null; loadProducts(); }
        document.getElementById("btn-seed-catalog")?.addEventListener("click", async () => {
          try {
            const res = await api("/api/admin/seed-catalog", { method: "POST", body: JSON.stringify({}) });
            toast(res.message || ("Imported " + (res.imported || 0)));
            drillMain = null; drillType = null; loadProducts();
          } catch (e) { toast(e.message, true); }
        });
      });
    });



    function renderProductsByClass(products) {
      const wrap = document.getElementById("products-by-class");
      const tbody = document.getElementById("products-tbody");
      if (!wrap && !tbody) return;
      const groups = {};
      (products || []).forEach(p => {
        const key = p.category_path || p.category || "Other";
        if (!groups[key]) groups[key] = [];
        groups[key].push(p);
      });
      const keys = Object.keys(groups).sort();
      let html = "";
      keys.forEach(k => {
        html += `<div class="admin-class-block"><div class="admin-class-head">${esc(k)} <span style="font-weight:400;color:var(--muted)">${groups[k].length}</span></div>`;
        html += `<table style="width:100%;font-size:0.9rem"><thead><tr><th>Name</th><th>Price</th><th>Active</th><th></th></tr></thead><tbody>`;
        groups[k].forEach(p => {
          html += `<tr>
            <td>${esc(p.name)}</td>
            <td>NPR ${Number(p.price).toLocaleString()}</td>
            <td>${p.active ? "Yes" : "No"}</td>
            <td style="white-space:nowrap">
              <button type="button" class="btn btn-sm btn-ghost" data-edit="${p.id}">Edit</button>
              <button type="button" class="btn btn-sm btn-ghost" data-toggle="${p.id}" data-active="${p.active}">${p.active ? "Disable" : "Enable"}</button>
              <button type="button" class="btn btn-sm btn-ghost" data-del="${p.id}" style="color:var(--color-danger)">Delete</button>
            </td>
          </tr>`;
        });
        html += `</tbody></table></div>`;
      });
      if (wrap) wrap.innerHTML = html || "<p>No products</p>";
      else if (tbody) {
        // fallback: leave tbody, also set wrap parent
      }
      // bind buttons
      const root = wrap || document.getElementById("tab-products");
      root.querySelectorAll("[data-edit]").forEach(b => b.addEventListener("click", () => {
        const p = products.find(x => String(x.id) === b.getAttribute("data-edit"));
        if (p && typeof editProduct === "function") editProduct(p);
      }));
      root.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", async () => {
        if (!confirm("Delete product?")) return;
        try {
          await api("/api/products/" + b.getAttribute("data-del"), { method: "DELETE" });
          toast("Deleted"); loadProducts();
        } catch (e) { toast(e.message, true); }
      }));
      root.querySelectorAll("[data-toggle]").forEach(b => b.addEventListener("click", async () => {
        const id = b.getAttribute("data-toggle");
        const p = products.find(x => String(x.id) === id);
        if (!p) return;
        try {
          await api("/api/products/" + id, { method: "PUT", body: JSON.stringify({ ...p, active: !p.active }) });
          toast(p.active ? "Disabled" : "Enabled"); loadProducts();
        } catch (e) { toast(e.message, true); }
      }));
    }

    // Neon data tools
    async function refreshDbStatus() {
      const box = document.getElementById("db-status-box");
      if (!box) return;
      try {
        const data = await api("/api/admin/db-status");
        box.innerHTML =
          "<strong>Primary (DATABASE_URL):</strong> " + (data.primary_ok ? "online" : (data.primary_configured ? "offline / limit" : "not set")) +
          (data.primary_product_count != null ? " — " + data.primary_product_count + " products" : "") + "<br>" +
          "<strong>Backup (DATABASE_URL_BACKUP):</strong> " + (data.backup_ok ? "online" : (data.backup_configured ? "offline / limit" : "not set")) +
          (data.backup_product_count != null ? " — " + data.backup_product_count + " products" : "") + "<br>" +
          "<strong>App using:</strong> " + (data.active || "—");
      } catch (e) {
        box.textContent = e.message || "Could not load DB status";
      }
    }

    document.getElementById("btn-refresh-db")?.addEventListener("click", refreshDbStatus);
    document.getElementById("btn-sync-backup")?.addEventListener("click", async () => {
      if (!confirm("Copy all products, branding and notice from BACKUP (old Neon) into PRIMARY (new Neon)? Existing products on primary can be replaced.")) return;
      try {
        const data = await api("/api/admin/sync-from-backup", { method: "POST", body: JSON.stringify({ replace: true }) });
        toast(data.message || "Synced");
        refreshDbStatus();
        loadProducts();
        loadBranding();
        loadNotice();
      } catch (e) {
        toast(e.message, true);
      }
    });
    document.getElementById("btn-export-active")?.addEventListener("click", () => {
      window.location.href = "/api/admin/export?source=active";
    });
    document.getElementById("btn-export-backup")?.addEventListener("click", () => {
      window.location.href = "/api/admin/export?source=backup";
    });
    document.getElementById("btn-import")?.addEventListener("click", async () => {
      let data;
      try {
        data = JSON.parse(document.getElementById("import-json").value || "{}");
      } catch {
        toast("Invalid JSON", true);
        return;
      }
      data.replace = document.getElementById("import-replace").checked;
      try {
        const res = await api("/api/admin/import", { method: "POST", body: JSON.stringify(data) });
        toast(res.message || "Imported");
        loadProducts();
        loadBranding();
        loadNotice();
        refreshDbStatus();
      } catch (e) {
        toast(e.message, true);
      }
    });

    // Init
    checkDb();
    loadProducts();
    loadNotice();
    loadBranding();
    setInterval(checkDb, 30000);
    // load db status when opening data tab
    document.querySelectorAll("nav button").forEach(btn => {
      btn.addEventListener("click", () => {
        if (btn.dataset.tab === "data") refreshDbStatus();
      });
    });
  </script>
</body>
</html>
"""


@app.route("/siteadmin/dashboard")
@login_required
def admin_dashboard():
    return render_template_string(
        DASHBOARD_HTML,
        username=session.get("admin_username", "admin"),
        csrf=csrf_token(),
    )


# ---------------------------------------------------------------------------
# Catch-all for SPA-ish admin paths (already handled)
# ---------------------------------------------------------------------------

@app.route("/siteadmin/")
@app.route("/siteadmin")
def admin_root():
    if session.get("admin_logged_in"):
        return redirect("/siteadmin/dashboard")
    return redirect("/siteadmin/login/admin")




# ---------------------------------------------------------------------------
# SSR helpers — products from DB first, bundled fallback second
# ---------------------------------------------------------------------------


def category_path_label(cat, sub="", ptype="", variant=""):
    tree = CATEGORY_TREE or {}
    parts = []
    main = tree.get(cat) or {}
    parts.append(main.get("label") or (cat or "").title() or "—")
    subs = main.get("subs") or {}
    sub_node = subs.get(sub) or {}
    if sub_node.get("label"):
        parts.append(sub_node["label"])
    items = sub_node.get("items") or {}
    # product_type key may be jeans etc
    if ptype:
        pretty = ptype.replace("-", " ").title()
        parts.append(pretty)
    if variant:
        parts.append(variant)
    return " → ".join(parts)


def product_row_dict(r):
    try:
        d = dict(r) if not isinstance(r, dict) else dict(r)
    except Exception:
        d = {}
    cat = (d.get("category") or "men")
    sub = d.get("subcategory") or ""
    ptype = d.get("product_type") or ""
    variant = d.get("variant") or ""
    try:
        price = int(d.get("price") or 0)
    except (TypeError, ValueError):
        price = 0
    return {
        "id": d.get("id"),
        "name": d.get("name") or "",
        "price": price,
        "image_url": d.get("image_url") or "",
        "description": d.get("description") or "",
        "category": cat,
        "subcategory": sub,
        "product_type": ptype,
        "variant": variant,
        "category_path": category_path_label(cat, sub, ptype, variant),
        "colors": parse_json_list(d.get("colors")),
        "sizes": parse_json_list(d.get("sizes")),
        "active": bool(d.get("active", True)),
    }

FALLBACK_PRODUCTS = []
def _load_fallback_catalog():
    global FALLBACK_PRODUCTS
    if FALLBACK_PRODUCTS:
        return FALLBACK_PRODUCTS
    candidates = [
        Path(__file__).resolve().parent / "fallback_catalog.json",
        Path(__file__).resolve().parent / "public" / "js" / "fallback_catalog.json",
        Path(__file__).resolve().parent.parent / "api" / "fallback_catalog.json",
        Path(__file__).resolve().parent.parent / "public" / "js" / "fallback_catalog.json",
        Path.cwd() / "api" / "fallback_catalog.json",
        Path.cwd() / "fallback_catalog.json",
    ]
    for p in candidates:
        try:
            if p.is_file():
                FALLBACK_PRODUCTS = json.loads(p.read_text(encoding="utf-8"))
                if FALLBACK_PRODUCTS:
                    return FALLBACK_PRODUCTS
        except Exception:
            continue
    return FALLBACK_PRODUCTS or []


def seed_catalog_if_empty(conn):
    """Copy hardcoded catalog into products table once so admin can edit images/prices."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM products")
            if cur.fetchone()[0] > 0:
                return 0
        catalog = _load_fallback_catalog()
        if not catalog:
            return 0
        n = 0
        with conn.cursor() as cur:
            for p in catalog:
                name = sanitize_str(p.get("name"), 200)
                if not name:
                    continue
                try:
                    price = int(p.get("price") or 0)
                except (TypeError, ValueError):
                    price = 0
                cur.execute("""
                    INSERT INTO products
                    (name, price, image_url, description, category, subcategory, product_type, variant, colors, sizes, active)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    name, max(0, price),
                    sanitize_str(p.get("image_url"), 500),
                    sanitize_str(p.get("description"), 2000),
                    sanitize_str(p.get("category"), 50) or "men",
                    sanitize_str(p.get("subcategory"), 80),
                    sanitize_str(p.get("product_type"), 80),
                    sanitize_str(p.get("variant"), 80),
                    json.dumps(p.get("colors") if isinstance(p.get("colors"), list) else []),
                    json.dumps(p.get("sizes") if isinstance(p.get("sizes"), list) else []),
                    bool(p.get("active", True)),
                ))
                n += 1
        return n
    except Exception as e:
        app.config["_seed_error"] = str(e)[:160]
        return 0

    global FALLBACK_PRODUCTS
    if FALLBACK_PRODUCTS:
        return FALLBACK_PRODUCTS
    for p in (
        Path(__file__).resolve().parent / "fallback_catalog.json",
        Path(__file__).resolve().parent.parent / "api" / "fallback_catalog.json",
    ):
        if p.is_file():
            try:
                FALLBACK_PRODUCTS = json.loads(p.read_text(encoding="utf-8"))
                return FALLBACK_PRODUCTS
            except Exception:
                pass
    return FALLBACK_PRODUCTS
_load_fallback_catalog()



def load_products_ssr(active_only=True):
    conn = get_connection()
    if not conn:
        prods = [p for p in FALLBACK_PRODUCTS if p.get("active")]
        return prods, "fallback"
    try:
        init_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if active_only:
                cur.execute("""
                    SELECT id, name, price, image_url, description, category, subcategory, product_type, variant, colors, sizes, active
                    FROM products WHERE active = TRUE ORDER BY id DESC
                """)
            else:
                cur.execute("""
                    SELECT id, name, price, image_url, description, category, subcategory, product_type, variant, colors, sizes, active
                    FROM products ORDER BY id DESC
                """)
            rows = cur.fetchall()
        products = []
        for r in rows:
            products.append(product_row_dict(r))
        if products:
            return products, "live"
        return [product_row_dict(p) for p in _load_fallback_catalog()], "fallback"
    except Exception:
        return [product_row_dict(p) for p in _load_fallback_catalog()], "fallback"
    finally:
        try:
            conn.close()
        except Exception:
            pass


def load_site_context():
    ctx = {
        "brand_name": "Atelier Lane",
        "logo_url": "",
        "favicon_url": "",
        "facebook_url": "",
        "instagram_url": "",
        "whatsapp": "",
        "notice": None,
        "year": datetime.now(NPT).year,
    }
    conn = get_connection()
    if not conn:
        return ctx
    try:
        init_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT logo_url, favicon_url, brand_name, facebook_url, instagram_url, whatsapp
                FROM website_settings WHERE id = 1
            """)
            row = cur.fetchone()
            if row:
                d = dict(row)
                ctx["logo_url"] = d.get("logo_url") or ""
                ctx["favicon_url"] = d.get("favicon_url") or ""
                ctx["brand_name"] = (d.get("brand_name") or "Atelier Lane").strip() or "Atelier Lane"
                ctx["facebook_url"] = d.get("facebook_url") or ""
                ctx["instagram_url"] = d.get("instagram_url") or ""
                ctx["whatsapp"] = d.get("whatsapp") or ""
            cur.execute("""
                SELECT title, message, image_url, button_text, button_url,
                       notice_type, enabled, start_date, end_date
                FROM homepage_notice WHERE id = 1
            """)
            n = cur.fetchone()
            if n and n["enabled"]:
                today = datetime.now(NPT).date()
                ok = True
                if n["start_date"] and today < n["start_date"]:
                    ok = False
                if n["end_date"] and today > n["end_date"]:
                    ok = False
                if ok:
                    ctx["notice"] = {
                        "title": n["title"] or "",
                        "message": n["message"] or "",
                        "image_url": n["image_url"] or "",
                        "button_text": n["button_text"] or "",
                        "button_url": n["button_url"] or "",
                        "notice_type": n["notice_type"] or "banner",
                        "enabled": True,
                    }
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return ctx


def _ssr_bundle(need_products=True, active_only=True):
    """One DB round-trip for settings + optional products (faster pages)."""
    ctx = {
        "brand_name": "Atelier Lane",
        "logo_url": "",
        "favicon_url": "",
        "facebook_url": "",
        "instagram_url": "",
        "whatsapp": "",
        "notice": None,
        "year": datetime.now(NPT).year,
        "products": [],
        "products_source": "fallback",
    }
    conn = get_connection()
    if not conn:
        if need_products:
            ctx["products"] = [product_row_dict(p) for p in _load_fallback_catalog() if p.get("active")]
        return ctx
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                cur.execute("""
                    SELECT logo_url, favicon_url, brand_name, facebook_url, instagram_url, whatsapp
                    FROM website_settings WHERE id = 1
                """)
                row = cur.fetchone()
                if row:
                    d = dict(row)
                    ctx["logo_url"] = d.get("logo_url") or ""
                    ctx["favicon_url"] = d.get("favicon_url") or ""
                    ctx["brand_name"] = (d.get("brand_name") or "Atelier Lane").strip() or "Atelier Lane"
                    ctx["facebook_url"] = d.get("facebook_url") or ""
                    ctx["instagram_url"] = d.get("instagram_url") or ""
                    ctx["whatsapp"] = d.get("whatsapp") or ""
            except Exception:
                pass
            try:
                cur.execute("""
                    SELECT title, message, image_url, button_text, button_url,
                           notice_type, enabled, start_date, end_date
                    FROM homepage_notice WHERE id = 1
                """)
                n = cur.fetchone()
                if n and n["enabled"]:
                    today = datetime.now(NPT).date()
                    ok = True
                    if n["start_date"] and today < n["start_date"]:
                        ok = False
                    if n["end_date"] and today > n["end_date"]:
                        ok = False
                    if ok:
                        ctx["notice"] = {
                            "title": n["title"] or "",
                            "message": n["message"] or "",
                            "image_url": n["image_url"] or "",
                            "button_text": n["button_text"] or "",
                            "button_url": n["button_url"] or "",
                            "notice_type": n["notice_type"] or "banner",
                            "enabled": True,
                        }
            except Exception:
                pass
            if need_products:
                try:
                    if active_only:
                        cur.execute("""
                            SELECT id, name, price, image_url, description, category, subcategory, product_type, variant, colors, sizes, active
                            FROM products WHERE active = TRUE ORDER BY id DESC LIMIT 100
                        """)
                    else:
                        cur.execute("""
                            SELECT id, name, price, image_url, description, category, subcategory, product_type, variant, colors, sizes, active
                            FROM products ORDER BY id DESC LIMIT 100
                        """)
                    rows = cur.fetchall()
                    products = []
                    for r in rows:
                        try:
                            products.append(product_row_dict(r))
                        except Exception:
                            products.append({
                                "id": r["id"], "name": r["name"], "price": r["price"],
                                "image_url": r["image_url"] or "", "description": r["description"] or "",
                                "category": r["category"] or "men", "subcategory": "", "product_type": "", "variant": "",
                                "category_path": r["category"] or "men",
                                "colors": parse_json_list(r["colors"]), "sizes": parse_json_list(r["sizes"]),
                                "active": bool(r["active"]),
                            })
                    if products:
                        ctx["products"] = products
                        ctx["products_source"] = "live"
                    else:
                        ctx["products"] = [product_row_dict(p) for p in _load_fallback_catalog()]
                except Exception:
                    ctx["products"] = [product_row_dict(p) for p in _load_fallback_catalog()]
        return ctx
    finally:
        try:
            conn.close()
        except Exception:
            pass


def render_page(template, **extra):
    # extra may already include full ctx from _ssr_bundle
    if "brand_name" not in extra:
        base = _ssr_bundle(need_products=False)
        base.update(extra)
        extra = base
    resp = make_response(render_template(template, **extra))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/")
def page_home():
    ctx = _ssr_bundle(need_products=True)
    ctx["page"] = "home"
    return render_page("home.html", **ctx)


@app.route("/shop")
@app.route("/shop.html")
def page_shop():
    cat = (request.args.get("cat") or "all").lower().strip()
    type_slug = (request.args.get("type") or request.args.get("sub") or "").lower().strip()
    ctx = _ssr_bundle(need_products=True)
    products = ctx.get("products") or []
    tree = CATEGORY_TREE or {}
    cat_label = ""
    type_label = ""
    type_chips = []
    if cat and cat != "all":
        node = tree.get(cat) or {}
        cat_label = node.get("label") or cat.replace("-", " ").title()
        products = [p for p in products if (p.get("category") or "").lower() == cat]
        # Build type chips from actual products
        counts = {}
        for p in products:
            t = (p.get("product_type") or p.get("subcategory") or "general").lower()
            if t not in counts:
                counts[t] = {"slug": t, "label": t.replace("-", " ").title(), "count": 0}
            counts[t]["count"] += 1
        type_chips = sorted(counts.values(), key=lambda x: x["label"])
        if type_slug:
            type_label = type_slug.replace("-", " ").title()
            products = [
                p for p in products
                if (p.get("product_type") or p.get("subcategory") or "general").lower() == type_slug
            ]
    ctx["products"] = products
    ctx["page"] = "shop"
    ctx["cat"] = cat
    ctx["type_slug"] = type_slug
    ctx["cat_label"] = cat_label
    ctx["type_label"] = type_label
    ctx["type_chips"] = type_chips
    return render_page("shop.html", **ctx)


@app.route("/product")
@app.route("/product.html")
def page_product():
    pid = request.args.get("id")
    ctx = _ssr_bundle(need_products=True)
    products = ctx.get("products") or []
    product = None
    for p in products:
        if str(p["id"]) == str(pid):
            product = p
            break
    related = []
    if product:
        related = [p for p in products if p["id"] != product["id"] and p.get("category") == product.get("category")][:4]
        if not related:
            related = [p for p in products if p["id"] != product["id"]][:4]
    ctx["product"] = product
    ctx["related"] = related
    ctx["page"] = "product"
    return render_page("product.html", **ctx)


@app.route("/checkout")
@app.route("/checkout.html")
def page_checkout():
    ctx = _ssr_bundle(need_products=False)
    ctx["page"] = "checkout"
    return render_page("checkout.html", **ctx)


@app.route("/contact")
@app.route("/contact.html")
def page_contact():
    ctx = _ssr_bundle(need_products=False)
    ctx["page"] = "contact"
    return render_page("contact.html", **ctx)



# ---------------------------------------------------------------------------
# Admin: export / import / sync between Neon primary & backup
# ---------------------------------------------------------------------------

def _connect_url(raw_url):
    if not raw_url or not HAS_PSYCOPG2:
        return None
    url = _normalize_db_url(raw_url)
    try:
        conn = psycopg2.connect(url, connect_timeout=8)
        conn.autocommit = True
        return conn
    except Exception as e:
        app.config["_last_db_error"] = str(e)[:200]
        return None


def _fetch_catalog(conn):
    init_schema(conn)
    out = {"products": [], "settings": {}, "notice": {}}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, name, price, image_url, description, category, subcategory, product_type, variant, colors, sizes, active
            FROM products ORDER BY id ASC
        """)
        for r in cur.fetchall():
            out["products"].append({
                "id": r["id"],
                "name": r["name"],
                "price": r["price"],
                "image_url": r["image_url"] or "",
                "description": r["description"] or "",
                "category": r["category"] or "men",
                "colors": parse_json_list(r["colors"]),
                "sizes": parse_json_list(r["sizes"]),
                "active": bool(r["active"]),
            })
        cur.execute("""
            SELECT logo_url, favicon_url, brand_name, facebook_url, instagram_url, whatsapp
            FROM website_settings WHERE id = 1
        """)
        s = cur.fetchone()
        if s:
            d = dict(s)
            out["settings"] = {
                "logo_url": d.get("logo_url") or "",
                "favicon_url": d.get("favicon_url") or "",
                "brand_name": d.get("brand_name") or "Atelier Lane",
                "facebook_url": d.get("facebook_url") or "",
                "instagram_url": d.get("instagram_url") or "",
                "whatsapp": d.get("whatsapp") or "",
            }
        cur.execute("""
            SELECT title, message, image_url, button_text, button_url,
                   notice_type, enabled, start_date, end_date
            FROM homepage_notice WHERE id = 1
        """)
        n = cur.fetchone()
        if n:
            out["notice"] = {
                "title": n["title"] or "",
                "message": n["message"] or "",
                "image_url": n["image_url"] or "",
                "button_text": n["button_text"] or "",
                "button_url": n["button_url"] or "",
                "notice_type": n["notice_type"] or "banner",
                "enabled": bool(n["enabled"]),
                "start_date": n["start_date"].isoformat() if n["start_date"] else None,
                "end_date": n["end_date"].isoformat() if n["end_date"] else None,
            }
    return out


def _import_catalog(conn, data, replace=False):
    init_schema(conn)
    products = data.get("products") or []
    settings = data.get("settings") or {}
    notice = data.get("notice") or {}
    with conn.cursor() as cur:
        if replace:
            cur.execute("DELETE FROM products")
        for p in products:
            name = sanitize_str(p.get("name"), 200)
            if not name:
                continue
            try:
                price = int(p.get("price") or 0)
            except (TypeError, ValueError):
                price = 0
            colors = json.dumps(p.get("colors") if isinstance(p.get("colors"), list) else [])
            sizes = json.dumps(p.get("sizes") if isinstance(p.get("sizes"), list) else [])
            cur.execute("""
                INSERT INTO products (name, price, image_url, description, category, colors, sizes, active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                name, max(0, price),
                sanitize_str(p.get("image_url"), 500),
                sanitize_str(p.get("description"), 2000),
                sanitize_str(p.get("category"), 50) or "men",
                colors, sizes, bool(p.get("active", True)),
            ))
        if settings:
            cur.execute("""
                UPDATE website_settings SET
                    logo_url = COALESCE(NULLIF(%s, ''), logo_url),
                    favicon_url = COALESCE(NULLIF(%s, ''), favicon_url),
                    brand_name = COALESCE(NULLIF(%s, ''), brand_name),
                    facebook_url = COALESCE(%s, facebook_url),
                    instagram_url = COALESCE(%s, instagram_url),
                    whatsapp = COALESCE(%s, whatsapp),
                    updated_at = NOW()
                WHERE id = 1
            """, (
                sanitize_str(settings.get("logo_url"), 500),
                sanitize_str(settings.get("favicon_url"), 500),
                sanitize_str(settings.get("brand_name"), 120) or "Atelier Lane",
                sanitize_str(settings.get("facebook_url"), 500),
                sanitize_str(settings.get("instagram_url"), 500),
                sanitize_str(settings.get("whatsapp"), 40),
            ))
        if notice:
            cur.execute("""
                UPDATE homepage_notice SET
                    title = %s, message = %s, image_url = %s,
                    button_text = %s, button_url = %s, notice_type = %s,
                    enabled = %s, start_date = %s, end_date = %s, updated_at = NOW()
                WHERE id = 1
            """, (
                sanitize_str(notice.get("title"), 200),
                sanitize_str(notice.get("message"), 2000),
                sanitize_str(notice.get("image_url"), 500),
                sanitize_str(notice.get("button_text"), 100),
                sanitize_str(notice.get("button_url"), 500),
                sanitize_str(notice.get("notice_type"), 20) or "banner",
                bool(notice.get("enabled", False)),
                notice.get("start_date") or None,
                notice.get("end_date") or None,
            ))
    return len(products)



@app.route("/api/admin/seed-catalog", methods=["POST"])
@login_required
def admin_seed_catalog():
    """Import hardcoded catalog into DB (only fills when empty, or replace if requested)."""
    if not validate_csrf():
        return jsonify({"error": "Invalid CSRF token"}), 403
    conn = get_connection()
    if not conn:
        return jsonify({"error": "Database unavailable"}), 503
    try:
        data = request.get_json(silent=True) or {}
        replace = bool(data.get("replace"))
        init_schema(conn)
        with conn.cursor() as cur:
            if replace:
                cur.execute("DELETE FROM products")
            cur.execute("SELECT COUNT(*) FROM products")
            count = cur.fetchone()[0]
        if count > 0 and not replace:
            return jsonify({"ok": True, "message": f"DB already has {count} products. Edit them in Products tab. Pass replace:true to wipe & re-import catalog."})
        n = seed_catalog_if_empty(conn)
        if replace:
            # force seed after delete
            n = seed_catalog_if_empty(conn)
        return jsonify({"ok": True, "imported": n, "message": f"Imported {n} catalog products. You can edit names, prices and images now."})
    except Exception as e:
        return jsonify({"error": str(e)[:180]}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass

@app.route("/api/admin/export", methods=["GET"])
@login_required
def admin_export():
    """Download products + settings + notice from the currently connected DB."""
    source = request.args.get("source", "active")  # active | primary | backup
    primary = os.environ.get("DATABASE_URL", "").strip()
    backup = os.environ.get("DATABASE_URL_BACKUP", "").strip()
    if source == "backup":
        conn = _connect_url(backup)
        label = "backup"
    elif source == "primary":
        conn = _connect_url(primary)
        label = "primary"
    else:
        conn = get_connection()
        label = app.config.get("_db_active") or "active"
    if not conn:
        return jsonify({"error": f"Cannot connect to {label} database. Is the Neon project awake?"}), 503
    try:
        data = _fetch_catalog(conn)
        data["exported_from"] = label
        data["exported_at"] = datetime.now(NPT).isoformat()
        resp = make_response(json.dumps(data, ensure_ascii=False, indent=2))
        resp.headers["Content-Type"] = "application/json; charset=utf-8"
        resp.headers["Content-Disposition"] = f'attachment; filename="atelier-lane-export-{label}.json"'
        return resp
    except Exception as e:
        return jsonify({"error": str(e)[:180]}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.route("/api/admin/import", methods=["POST"])
@login_required
def admin_import():
    if not validate_csrf():
        return jsonify({"error": "Invalid CSRF token"}), 403
    conn = get_connection()
    if not conn:
        return jsonify({"error": "Database unavailable. Cannot import."}), 503
    try:
        data = request.get_json(silent=True) or {}
        replace = bool(data.get("replace", False))
        count = _import_catalog(conn, data, replace=replace)
        return jsonify({"ok": True, "imported_products": count, "message": f"Imported {count} products into active DB."})
    except Exception as e:
        return jsonify({"error": f"Import failed: {str(e)[:180]}"}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.route("/api/admin/sync-from-backup", methods=["POST"])
@login_required
def admin_sync_from_backup():
    """Copy products/settings/notice from DATABASE_URL_BACKUP → primary DATABASE_URL."""
    if not validate_csrf():
        return jsonify({"error": "Invalid CSRF token"}), 403
    primary = os.environ.get("DATABASE_URL", "").strip()
    backup = os.environ.get("DATABASE_URL_BACKUP", "").strip()
    if not primary or not backup:
        return jsonify({
            "error": "Set both DATABASE_URL (new/active) and DATABASE_URL_BACKUP (old Neon with your data) in Vercel env."
        }), 400
    if primary == backup:
        return jsonify({"error": "Primary and backup URLs are the same."}), 400

    src = _connect_url(backup)
    if not src:
        return jsonify({
            "error": "Cannot connect to BACKUP (old) database. Wake the old Neon project or try again when compute is available."
        }), 503
    dst = _connect_url(primary)
    if not dst:
        src.close()
        return jsonify({"error": "Cannot connect to PRIMARY (new) database."}), 503
    try:
        data = _fetch_catalog(src)
        replace = bool((request.get_json(silent=True) or {}).get("replace", True))
        count = _import_catalog(dst, data, replace=replace)
        return jsonify({
            "ok": True,
            "synced_products": count,
            "message": f"Copied {count} products + settings + notice from old Neon → new Neon.",
        })
    except Exception as e:
        return jsonify({"error": f"Sync failed: {str(e)[:180]}"}), 500
    finally:
        try:
            src.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass


@app.route("/api/admin/db-status", methods=["GET"])
@login_required
def admin_db_status():
    primary = os.environ.get("DATABASE_URL", "").strip()
    backup = os.environ.get("DATABASE_URL_BACKUP", "").strip()
    result = {
        "primary_configured": bool(primary),
        "backup_configured": bool(backup),
        "primary_ok": False,
        "backup_ok": False,
        "active": app.config.get("_db_active"),
    }
    if primary:
        c = _connect_url(primary)
        if c:
            result["primary_ok"] = True
            try:
                with c.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM products")
                    result["primary_product_count"] = cur.fetchone()[0]
            except Exception:
                result["primary_product_count"] = None
            c.close()
    if backup:
        c = _connect_url(backup)
        if c:
            result["backup_ok"] = True
            try:
                init_schema(c)
                with c.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM products")
                    result["backup_product_count"] = cur.fetchone()[0]
            except Exception:
                result["backup_product_count"] = None
            c.close()
    return jsonify(result)




DEFAULT_DEVELOPERS = [
    ("Argon Bhujel", "Full stack web & Android APK developer", 1),
    ("Manzil Bhujel", "Front end developer & data analyst", 2),
    ("Dikshya Khanal", "Front end developer", 3),
    ("Tularam Limbu", "UI/UX designer", 4),
]


def ensure_developers(conn):
    """Insert fixed developer rows if missing (by name)."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        for name, role, order in DEFAULT_DEVELOPERS:
            cur.execute(
                "SELECT id FROM team_members WHERE team_type = 'developer' AND name = %s",
                (name,),
            )
            if not cur.fetchone():
                cur.execute(
                    """INSERT INTO team_members
                       (team_type, name, role, bio, photo_url, enabled, sort_order, locked)
                       VALUES ('developer', %s, %s, '', '', TRUE, %s, TRUE)""",
                    (name, role, order),
                )


def load_teams():
    """Return developers + owners from DB. Seeds developers when needed."""
    fallback = [
        {"id": i + 1, "team_type": "developer", "name": n, "role": r, "bio": "",
         "photo_url": "", "enabled": True, "sort_order": o, "locked": True}
        for i, (n, r, o) in enumerate(DEFAULT_DEVELOPERS)
    ]
    conn = get_connection()
    if not conn:
        return fallback, []
    try:
        init_schema(conn)
        ensure_developers(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, team_type, name, role, bio, photo_url, enabled, sort_order, locked
                FROM team_members ORDER BY team_type, sort_order, id
            """)
            rows = [dict(r) for r in cur.fetchall()]
        devs = [r for r in rows if r.get("team_type") == "developer"]
        owners = [r for r in rows if r.get("team_type") == "owner"]
        return (devs or fallback), owners
    except Exception:
        return fallback, []
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.route("/teams")
@app.route("/teams.html")
def page_teams():
    section = (request.args.get("section") or "all").lower()
    devs, owners = load_teams()
    ctx = _ssr_bundle(need_products=False)
    ctx.update({
        "page": "teams",
        "developers": devs,
        "owners": owners,
        "section": section if section in ("developers", "owners") else "all",
    })
    return render_page("teams.html", **ctx)


@app.route("/api/admin/team", methods=["GET"])
@login_required
def admin_team_list():
    devs, owners = load_teams()
    return jsonify({"developers": devs, "owners": owners})


@app.route("/api/admin/team", methods=["POST"])
@login_required
def admin_team_create():
    """Create owner member only (developers are fixed)."""
    if not validate_csrf():
        return jsonify({"error": "Invalid CSRF token"}), 403
    data = request.get_json(silent=True) or {}
    team_type = sanitize_str(data.get("team_type"), 20) or "owner"
    if team_type != "owner":
        return jsonify({"error": "Only owner team members can be added"}), 400
    name = sanitize_str(data.get("name"), 150)
    if not name:
        return jsonify({"error": "Name required"}), 400
    conn = get_connection()
    if not conn:
        return jsonify({"error": "Database unavailable"}), 503
    try:
        init_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO team_members (team_type, name, role, bio, photo_url, enabled, sort_order, locked)
                VALUES ('owner', %s, %s, %s, %s, %s, %s, FALSE)
                RETURNING id, team_type, name, role, bio, photo_url, enabled, sort_order, locked
            """, (
                name,
                sanitize_str(data.get("role"), 200),
                sanitize_str(data.get("bio"), 1000),
                sanitize_str(data.get("photo_url"), 500),
                bool(data.get("enabled", True)),
                int(data.get("sort_order") or 0),
            ))
            row = dict(cur.fetchone())
        return jsonify({"member": row}), 201
    except Exception as e:
        return jsonify({"error": str(e)[:160]}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.route("/api/admin/team/<int:mid>", methods=["PUT"])
@login_required
def admin_team_update(mid):
    if not validate_csrf():
        return jsonify({"error": "Invalid CSRF token"}), 403
    data = request.get_json(silent=True) or {}
    conn = get_connection()
    if not conn:
        return jsonify({"error": "Database unavailable — set DATABASE_URL to save photos"}), 503
    try:
        init_schema(conn)
        ensure_developers(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM team_members WHERE id = %s", (mid,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Member not found. Refresh the Teams tab and try again."}), 404
            locked = bool(row["locked"]) or row["team_type"] == "developer"
            # Allow longer image CDN URLs
            photo_url = sanitize_str(data.get("photo_url"), 800) if "photo_url" in data else None
            if photo_url is not None and photo_url != "" and not is_safe_image_url(photo_url):
                return jsonify({"error": "Invalid photo URL — use https:// link (ImgBB, Cloudinary, etc.)"}), 400
            enabled = data.get("enabled")
            if isinstance(enabled, str):
                enabled = enabled.lower() in ("1", "true", "yes", "on")
            if locked:
                # Developers: photo + enabled only (always set photo when provided)
                if "photo_url" in data:
                    cur.execute("""
                        UPDATE team_members SET
                            photo_url = %s,
                            enabled = COALESCE(%s, enabled),
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, team_type, name, role, bio, photo_url, enabled, sort_order, locked
                    """, (photo_url or "", enabled if enabled is not None else None, mid))
                else:
                    cur.execute("""
                        UPDATE team_members SET
                            enabled = COALESCE(%s, enabled),
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, team_type, name, role, bio, photo_url, enabled, sort_order, locked
                    """, (enabled if enabled is not None else None, mid))
            else:
                cur.execute("""
                    UPDATE team_members SET
                        name = COALESCE(NULLIF(%s, ''), name),
                        role = COALESCE(%s, role),
                        bio = COALESCE(%s, bio),
                        photo_url = COALESCE(%s, photo_url),
                        enabled = COALESCE(%s, enabled),
                        sort_order = COALESCE(%s, sort_order),
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, team_type, name, role, bio, photo_url, enabled, sort_order, locked
                """, (
                    sanitize_str(data.get("name"), 150),
                    sanitize_str(data.get("role"), 200) if "role" in data else None,
                    sanitize_str(data.get("bio"), 1000) if "bio" in data else None,
                    photo_url if "photo_url" in data else None,
                    enabled if enabled is not None else None,
                    int(data["sort_order"]) if data.get("sort_order") is not None else None,
                    mid,
                ))
            out = dict(cur.fetchone())
        return jsonify({"ok": True, "member": out, "message": "Saved"})
    except Exception as e:
        return jsonify({"error": str(e)[:160]}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.route("/api/admin/team/<int:mid>", methods=["DELETE"])
@login_required
def admin_team_delete(mid):
    if not validate_csrf():
        return jsonify({"error": "Invalid CSRF token"}), 403
    conn = get_connection()
    if not conn:
        return jsonify({"error": "Database unavailable"}), 503
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT locked, team_type FROM team_members WHERE id = %s", (mid,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Not found"}), 404
            if row["locked"] or row["team_type"] == "developer":
                return jsonify({"error": "Developer team members cannot be deleted"}), 403
            cur.execute("DELETE FROM team_members WHERE id = %s", (mid,))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)[:160]}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Local development entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=5000)
