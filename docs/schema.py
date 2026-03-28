# MongoDB Schema Documentation
# Database: urlshortener

# ─────────────────────────────────────────────
# Collection: urls
# ─────────────────────────────────────────────
urls_schema = {
    "short_id":          str,    # unique, indexed — e.g. "abc1234"
    "original_url":      str,    # the destination URL
    "created_at":        datetime,
    "created_by_ip":     str,
    "total_clicks":      int,    # incremented on each /go/<id> visit
    "unique_ips":        list,   # list of unique visitor IPs (addToSet)
    "tokens_generated":  int,    # incremented each time a token is issued
}

# ─────────────────────────────────────────────
# Collection: tokens
# ─────────────────────────────────────────────
tokens_schema = {
    "token":       str,      # unique — secrets.token_urlsafe(32)
    "short_id":    str,      # which link this token unlocks
    "ip":          str,      # IP that generated the token
    "created_at":  datetime,
    "expires_at":  datetime, # TTL index auto-deletes after expiry
    "used":        bool,     # False until /verify consumes it
    "used_at":     datetime, # set when consumed (optional)
    "used_by_ip":  str,      # set when consumed (optional)
}

# ─────────────────────────────────────────────
# Collection: clicks
# ─────────────────────────────────────────────
clicks_schema = {
    "short_id":   str,
    "ip":         str,
    "user_agent": str,
    "is_unique":  bool,
    "created_at": datetime,
    "step":       str,  # "entry"
}

# ─────────────────────────────────────────────
# Collection: ratelimits
# ─────────────────────────────────────────────
ratelimits_schema = {
    "key":        str,      # "{ip}:{action}"
    "created_at": datetime,
    "expires_at": datetime, # TTL index auto-deletes
}
