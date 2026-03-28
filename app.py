"""
URL Shortener + Token Verification System
Designed for Telegram bot integration and ad monetization
"""

import os
import uuid
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (
    Flask, request, jsonify, render_template,
    redirect, abort, session, g
)
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError
import string
import random

# ─────────────────────────────────────────────
# App Configuration
# ─────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ─────────────────────────────────────────────
# MongoDB Setup
# ─────────────────────────────────────────────
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME   = os.environ.get("DB_NAME", "urlshortener")

client = MongoClient(MONGO_URI)
db     = client[DB_NAME]

# Collections
urls_col    = db["urls"]       # shortened URLs
tokens_col  = db["tokens"]     # verification tokens
clicks_col  = db["clicks"]     # click / analytics events
ratelimit_col = db["ratelimits"]

# Indexes (run once; harmless to re-run)
urls_col.create_index("short_id", unique=True)
tokens_col.create_index("token", unique=True)
tokens_col.create_index("expires_at", expireAfterSeconds=0)   # TTL index auto-cleans
clicks_col.create_index([("short_id", ASCENDING), ("created_at", ASCENDING)])
ratelimit_col.create_index("expires_at", expireAfterSeconds=0)

# ─────────────────────────────────────────────
# Ad Network Placeholders
# Replace these with your real links/scripts
# ─────────────────────────────────────────────
AD_CONFIG = {
    # PopAds: paste your site-specific script tag content here
    "popads_script": os.environ.get("POPADS_SCRIPT", "<!-- PopAds script placeholder -->"),

    # Adsterra Direct Link (user is redirected here briefly)
    "adsterra_url": os.environ.get("ADSTERRA_URL", "https://www.adsterra.com"),

    # Monetag Smart Link (opened when user clicks Continue)
    "monetag_url": os.environ.get("MONETAG_URL", "https://www.monetag.com"),

    # How long the final URL token is valid (minutes)
    "token_ttl_minutes": int(os.environ.get("TOKEN_TTL", "5")),

    # Countdown seconds on the timer page
    "countdown_seconds": int(os.environ.get("COUNTDOWN", "10")),
}

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
ALPHABET = string.ascii_letters + string.digits  # 62 chars

def generate_short_id(length: int = 7) -> str:
    """Generate a random alphanumeric short ID."""
    return "".join(random.choices(ALPHABET, k=length))

def get_client_ip() -> str:
    """Return real IP respecting common proxy headers."""
    for header in ("X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()
    return request.remote_addr or "unknown"

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def is_bot(user_agent: str) -> bool:
    """Very basic bot-detection by user-agent string."""
    bot_keywords = [
        "bot", "crawl", "spider", "slurp", "wget",
        "curl", "python-requests", "go-http", "java/",
        "headlesschrome", "phantomjs", "selenium"
    ]
    ua = (user_agent or "").lower()
    return any(kw in ua for kw in bot_keywords)

# ─────────────────────────────────────────────
# Rate Limiting (per IP, per endpoint)
# ─────────────────────────────────────────────
RATE_LIMITS = {
    "create": {"max": 20, "window": 3600},   # 20 creates/hour
    "go":     {"max": 60, "window": 3600},   # 60 redirects/hour
    "verify": {"max": 30, "window": 3600},   # 30 verifies/hour
}

def check_rate_limit(ip: str, action: str) -> bool:
    """Returns True if request is allowed, False if rate-limited."""
    cfg = RATE_LIMITS.get(action, {"max": 30, "window": 3600})
    key = f"{ip}:{action}"
    now = utcnow()
    window_start = now - timedelta(seconds=cfg["window"])

    count = ratelimit_col.count_documents({
        "key": key,
        "created_at": {"$gte": window_start}
    })
    if count >= cfg["max"]:
        return False

    ratelimit_col.insert_one({
        "key": key,
        "created_at": now,
        "expires_at": now + timedelta(seconds=cfg["window"])
    })
    return True

def require_rate_limit(action: str):
    """Decorator that enforces rate limiting."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            ip = get_client_ip()
            if not check_rate_limit(ip, action):
                return jsonify({"error": "Rate limit exceeded. Try again later."}), 429
            return f(*args, **kwargs)
        return wrapped
    return decorator

# ─────────────────────────────────────────────
# URL Management
# ─────────────────────────────────────────────

@app.route("/create", methods=["POST"])
@require_rate_limit("create")
def create_short_url():
    """
    POST /create
    Body (JSON): { "url": "https://example.com", "custom_id": "optional" }
    Returns: { "short_id": "abc1234", "short_url": "https://host/go/abc1234" }
    """
    data = request.get_json(silent=True) or {}
    original_url = (data.get("url") or "").strip()

    if not original_url:
        return jsonify({"error": "URL is required"}), 400
    if not original_url.startswith(("http://", "https://")):
        return jsonify({"error": "URL must start with http:// or https://"}), 400
    if len(original_url) > 2048:
        return jsonify({"error": "URL too long (max 2048 chars)"}), 400

    custom_id = (data.get("custom_id") or "").strip()
    if custom_id:
        if not all(c in ALPHABET + "-_" for c in custom_id) or len(custom_id) > 32:
            return jsonify({"error": "Custom ID: 1-32 alphanumeric/dash/underscore chars"}), 400
        short_id = custom_id
    else:
        # Retry loop in case of collision
        for _ in range(5):
            short_id = generate_short_id()
            if not urls_col.find_one({"short_id": short_id}):
                break
        else:
            return jsonify({"error": "Could not generate unique ID, try again"}), 500

    doc = {
        "short_id":    short_id,
        "original_url": original_url,
        "created_at":  utcnow(),
        "created_by_ip": get_client_ip(),
        "total_clicks": 0,
        "unique_ips":   [],
        "tokens_generated": 0,
    }

    try:
        urls_col.insert_one(doc)
    except DuplicateKeyError:
        return jsonify({"error": "Short ID already taken"}), 409

    base = request.host_url.rstrip("/")
    return jsonify({
        "short_id":  short_id,
        "short_url": f"{base}/go/{short_id}",
        "original_url": original_url,
    }), 201


# ─────────────────────────────────────────────
# Redirect + Ad Flow
# ─────────────────────────────────────────────

@app.route("/go/<short_id>")
@require_rate_limit("go")
def redirect_flow(short_id: str):
    """
    Entry point for the monetization flow.
    Step 1 – Shows the loading/ad page (popunder fires here).
    """
    url_doc = urls_col.find_one({"short_id": short_id})
    if not url_doc:
        abort(404)

    ip = get_client_ip()
    ua = request.headers.get("User-Agent", "")

    # Basic bot rejection
    if is_bot(ua):
        abort(403)

    # Log click
    is_unique = ip not in url_doc.get("unique_ips", [])
    clicks_col.insert_one({
        "short_id":  short_id,
        "ip":        ip,
        "user_agent": ua,
        "is_unique": is_unique,
        "created_at": utcnow(),
        "step": "entry",
    })

    # Update counters
    update = {"$inc": {"total_clicks": 1}}
    if is_unique:
        update["$addToSet"] = {"unique_ips": ip}
    urls_col.update_one({"short_id": short_id}, update)

    # Store flow state in session
    session["flow_short_id"] = short_id
    session["flow_step"]     = 1
    session["flow_ip"]       = ip

    return render_template(
        "step1_loading.html",
        short_id=short_id,
        adsterra_url=AD_CONFIG["adsterra_url"],
        popads_script=AD_CONFIG["popads_script"],
        countdown=AD_CONFIG["countdown_seconds"],
    )


@app.route("/step/timer/<short_id>")
def step_timer(short_id: str):
    """Step 2 – 10-second countdown timer page."""
    _require_flow_session(short_id, expected_step=1)
    session["flow_step"] = 2

    return render_template(
        "step2_timer.html",
        short_id=short_id,
        countdown=AD_CONFIG["countdown_seconds"],
        monetag_url=AD_CONFIG["monetag_url"],
    )


@app.route("/step/verify/<short_id>")
def step_verify(short_id: str):
    """Step 3 – Verification page (token generated on arrival)."""
    _require_flow_session(short_id, expected_step=2)

    url_doc = urls_col.find_one({"short_id": short_id})
    if not url_doc:
        abort(404)

    ip = get_client_ip()

    # Generate token
    token_str = secrets.token_urlsafe(32)
    now = utcnow()
    tokens_col.insert_one({
        "token":      token_str,
        "short_id":   short_id,
        "ip":         ip,
        "created_at": now,
        "expires_at": now + timedelta(minutes=AD_CONFIG["token_ttl_minutes"]),
        "used":       False,
    })
    urls_col.update_one({"short_id": short_id}, {"$inc": {"tokens_generated": 1}})

    session["flow_step"]  = 3
    session["flow_token"] = token_str

    return render_template(
        "step3_verify.html",
        short_id=short_id,
        token=token_str,
        ttl_minutes=AD_CONFIG["token_ttl_minutes"],
    )


@app.route("/step/success/<short_id>")
def step_success(short_id: str):
    """Step 4 – Success / access granted page."""
    _require_flow_session(short_id, expected_step=3)

    token_str   = session.get("flow_token")
    result      = _do_verify_token(token_str, get_client_ip())
    if not result["valid"]:
        return render_template("error.html", message=result["reason"]), 400

    url_doc = urls_col.find_one({"short_id": short_id})
    session.pop("flow_short_id", None)
    session.pop("flow_step",     None)
    session.pop("flow_token",    None)

    return render_template(
        "step4_success.html",
        original_url=url_doc["original_url"],
        short_id=short_id,
    )


# ─────────────────────────────────────────────
# Token API
# ─────────────────────────────────────────────

@app.route("/verify")
@require_rate_limit("verify")
def verify_token_endpoint():
    """
    GET /verify?token=XYZ
    Used by the frontend verify button.
    Returns JSON: { valid, reason }
    """
    token_str = request.args.get("token", "").strip()
    if not token_str:
        return jsonify({"valid": False, "reason": "Token required"}), 400

    ip     = get_client_ip()
    result = _do_verify_token(token_str, ip)
    status = 200 if result["valid"] else 400
    return jsonify(result), status


@app.route("/api/check_token")
def api_check_token():
    """
    GET /api/check_token?token=XYZ
    Telegram bot integration endpoint.
    Does NOT consume the token (read-only check).
    Returns: { valid: true/false, short_id, expires_at, used }
    """
    token_str = request.args.get("token", "").strip()
    if not token_str:
        return jsonify({"valid": False, "reason": "Token required"}), 400

    doc = tokens_col.find_one({"token": token_str})
    if not doc:
        return jsonify({"valid": False, "reason": "Token not found"})

    now = utcnow()
    expired = doc["expires_at"].replace(tzinfo=timezone.utc) < now

    return jsonify({
        "valid":      not expired and not doc["used"],
        "short_id":   doc.get("short_id"),
        "expires_at": doc["expires_at"].isoformat(),
        "used":       doc["used"],
        "expired":    expired,
    })


# ─────────────────────────────────────────────
# Analytics
# ─────────────────────────────────────────────

@app.route("/stats/<short_id>")
def stats(short_id: str):
    """
    GET /stats/<short_id>
    Returns basic analytics as JSON.
    """
    url_doc = urls_col.find_one({"short_id": short_id}, {"unique_ips": 0, "_id": 0})
    if not url_doc:
        abort(404)

    total   = url_doc.get("total_clicks", 0)
    tokens  = url_doc.get("tokens_generated", 0)
    unique  = len(url_doc.get("unique_ips", [])) if "unique_ips" in url_doc else 0

    # Re-fetch with unique_ips for count
    url_doc2 = urls_col.find_one({"short_id": short_id})
    unique = len(url_doc2.get("unique_ips", []))

    conversion = round((tokens / total * 100), 2) if total else 0

    return jsonify({
        "short_id":         short_id,
        "original_url":     url_doc["original_url"],
        "total_clicks":     total,
        "unique_visitors":  unique,
        "tokens_generated": tokens,
        "conversion_rate":  f"{conversion}%",
        "created_at":       url_doc["created_at"].isoformat(),
    })


# ─────────────────────────────────────────────
# Frontend Pages
# ─────────────────────────────────────────────

@app.route("/")
def index():
    """Landing / URL creation page."""
    return render_template("index.html")


# ─────────────────────────────────────────────
# Internal Helpers
# ─────────────────────────────────────────────

def _require_flow_session(short_id: str, expected_step: int):
    """Abort if session doesn't reflect correct flow state."""
    if (session.get("flow_short_id") != short_id or
            session.get("flow_step") != expected_step):
        abort(403)


def _do_verify_token(token_str: str, ip: str) -> dict:
    """Consume and validate a token. Returns { valid, reason }."""
    if not token_str:
        return {"valid": False, "reason": "Token required"}

    doc = tokens_col.find_one({"token": token_str})
    if not doc:
        return {"valid": False, "reason": "Token not found"}

    now = utcnow()
    if doc["expires_at"].replace(tzinfo=timezone.utc) < now:
        return {"valid": False, "reason": "Token expired"}

    if doc["used"]:
        return {"valid": False, "reason": "Token already used"}

    # Mark as used
    tokens_col.update_one({"token": token_str}, {"$set": {"used": True, "used_at": now, "used_by_ip": ip}})
    return {"valid": True, "reason": "OK", "short_id": doc.get("short_id")}


# ─────────────────────────────────────────────
# Error Handlers
# ─────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", message="Link not found or expired."), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", message="Access denied. Please start from the beginning."), 403

@app.errorhandler(429)
def too_many(e):
    return render_template("error.html", message="Too many requests. Please slow down."), 429


# ─────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    print(f"🚀  URL Shortener running on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
