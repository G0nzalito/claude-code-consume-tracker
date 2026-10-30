"""Claude Code usage widget for Glance.

Glance polls this service as an `extension` widget. The service reads the Claude
Code OAuth credentials, refreshes them when needed, asks Anthropic for the
current session (5h) and weekly limits, and answers with HTML containing two
progress bars.

Stdlib only, so the container needs no pip install.
"""

import html
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CREDENTIALS_FILE = os.environ.get("CREDENTIALS_FILE", "/data/credentials.json")
STATIC_TOKEN = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
PORT = int(os.environ.get("PORT", "8080"))
MIN_FETCH_INTERVAL = int(os.environ.get("MIN_FETCH_INTERVAL", "45"))

USER_AGENT = "claude-code-usage-glance/1.0"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
# Refresh a bit before the real expiry so a request never races it.
EXPIRY_MARGIN_MS = 120_000

log = logging.getLogger("claude-usage")
_lock = threading.Lock()
_cache = {"at": 0.0, "data": None, "error": None}


class UsageError(Exception):
    pass


def _http_json(req, timeout=15):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read()[:200].decode("utf-8", "replace")
        raise UsageError(f"HTTP {e.code} from {req.full_url}: {body}") from e
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise UsageError(f"{req.full_url}: {e}") from e


def _load_credentials():
    try:
        with open(CREDENTIALS_FILE) as f:
            raw = json.load(f)
    except FileNotFoundError:
        raise UsageError(f"{CREDENTIALS_FILE} not found - see README, step 1")
    except json.JSONDecodeError as e:
        raise UsageError(f"{CREDENTIALS_FILE} is not valid JSON: {e}")
    # Claude Code stores {"claudeAiOauth": {...}}; accept the bare object too.
    return raw, raw.get("claudeAiOauth", raw)


def _save_credentials(raw):
    tmp = CREDENTIALS_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(raw, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, CREDENTIALS_FILE)
    except OSError:
        # Single-file bind mounts cannot be replaced; write in place instead.
        with open(CREDENTIALS_FILE, "w") as f:
            json.dump(raw, f)


def _access_token():
    if STATIC_TOKEN:
        return STATIC_TOKEN
    raw, creds = _load_credentials()
    if creds.get("expiresAt", 0) - EXPIRY_MARGIN_MS > time.time() * 1000:
        return creds["accessToken"]

    log.info("access token expired, refreshing")
    req = urllib.request.Request(
        TOKEN_URL,
        data=json.dumps(
            {
                "grant_type": "refresh_token",
                "refresh_token": creds["refreshToken"],
                "client_id": CLIENT_ID,
            }
        ).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    new = _http_json(req)
    creds["accessToken"] = new["access_token"]
    # The refresh token rotates; losing the new one would lock the service out.
    creds["refreshToken"] = new.get("refresh_token", creds["refreshToken"])
    creds["expiresAt"] = int(time.time() * 1000) + int(new["expires_in"]) * 1000
    _save_credentials(raw)
    return creds["accessToken"]


def _fetch_usage():
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {_access_token()}",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": USER_AGENT,
        },
    )
    return _http_json(req)


def get_usage():
    """Return (data, error, fetched_at). Serves the last good data on failure."""
    with _lock:
        if time.time() - _cache["at"] >= MIN_FETCH_INTERVAL:
            try:
                _cache["data"] = _fetch_usage()
                _cache["error"] = None
                _cache["fetched"] = time.time()
            except (UsageError, KeyError) as e:
                log.warning("fetch failed: %s", e)
                _cache["error"] = str(e)
            _cache["at"] = time.time()
        return _cache["data"], _cache["error"], _cache.get("fetched")


def _window(data, kind, legacy_key):
    """Find a limit by kind in `limits`, falling back to the flat legacy keys."""
    for lim in data.get("limits") or []:
        if lim.get("kind") == kind and lim.get("percent") is not None:
            return float(lim["percent"]), lim.get("resets_at")
    legacy = data.get(legacy_key) or {}
    if legacy.get("utilization") is not None:
        return float(legacy["utilization"]), legacy.get("resets_at")
    return None


def _until(iso):
    if not iso:
        return ""
    secs = int((datetime.fromisoformat(iso) - datetime.now(timezone.utc)).total_seconds())
    if secs <= 0:
        return "resets now"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"resets in {d}d {h}h"
    if h:
        return f"resets in {h}h {m}m"
    return f"resets in {m}m"


def _bar_color(pct):
    if pct >= 90:
        return "var(--color-negative, #e5484d)"
    if pct >= 70:
        return "var(--color-primary, #f0a020)"
    return "var(--color-positive, #46a758)"


def _bar(label, window):
    if window is None:
        return (
            f'<div style="margin-bottom:14px"><span class="color-subdue">{html.escape(label)}'
            "</span> <span class=\"color-subdue\">- no data</span></div>"
        )
    pct, resets = window
    width = max(0.0, min(100.0, pct))
    return f"""
<div style="margin-bottom:14px">
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:5px">
    <span class="color-highlight">{html.escape(label)}</span>
    <span class="size-h4" style="color:{_bar_color(pct)}">{pct:.0f}%</span>
  </div>
  <div style="height:10px;border-radius:5px;overflow:hidden;background:var(--color-widget-background-highlight, rgba(128,128,128,.25))">
    <div style="height:100%;width:{width:.1f}%;border-radius:5px;background:{_bar_color(pct)};transition:width .4s"></div>
  </div>
  <div class="size-h6 color-subdue" style="margin-top:4px">{html.escape(_until(resets))}</div>
</div>"""


def render():
    data, error, fetched = get_usage()
    if data is None:
        return f'<p class="color-negative">Could not load Claude usage.</p><p class="size-h6 color-subdue">{html.escape(error or "unknown error")}</p>'
    body = _bar("Session (5h)", _window(data, "session", "five_hour"))
    body += _bar("Weekly", _window(data, "weekly_all", "seven_day"))
    if error:
        age = int((time.time() - fetched) // 60)
        body += f'<p class="size-h6 color-negative">Showing data from {age}m ago - refresh failing: {html.escape(error)}</p>'
    return body


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            payload, ctype, extra = b"ok", "text/plain", {}
        else:
            payload = render().encode()
            ctype = "text/html; charset=utf-8"
            extra = {
                "Widget-Title": "Claude Code",
                "Widget-Content-Type": "html",
            }
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("listening on :%d", PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
