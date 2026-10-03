"""Local, read-only analytics service for the Terra travel advisor."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(path):
        try:
            with open(path, encoding="utf-8") as env_file:
                for line in env_file:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    name, value = line.split("=", 1)
                    name, value = name.strip(), value.strip().strip("\"'")
                    if name and name not in os.environ:
                        os.environ[name] = value
        except OSError:
            return False
        return True

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
DB_PATH = Path(os.getenv("RASA_TRACKER_DB", ROOT / "db" / "conversation.db"))
HANDOVER_STATE_PATH = ROOT / "db" / "admin_handover_state.json"
RASA_API_URL = os.getenv("RASA_API_URL", "http://127.0.0.1:5005").rstrip("/")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
SESSION_SECRET = secrets.token_bytes(32)
ALLOWED_ORIGINS = {"http://127.0.0.1:5173", "http://localhost:5173"} | {
    origin.strip() for origin in os.getenv("ADMIN_ALLOWED_ORIGINS", "").split(",") if origin.strip()
}
ADMIN_HOST = os.getenv("ADMIN_HOST", "127.0.0.1")
ADMIN_PORT = int(os.getenv("ADMIN_PORT", "8060"))
SESSION_SECONDS = 60 * 60 * 8
AUTH_DISABLED_FOR_LOCAL_TESTING = False

def token_is_valid(candidate):
    return bool(ADMIN_TOKEN) and hmac.compare_digest(candidate, ADMIN_TOKEN)

def make_session():
    stamp = str(int(time.time())).encode()
    sig = hmac.new(SESSION_SECRET, stamp, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(stamp + b"|" + sig).decode().rstrip("=")

def session_is_valid(value):
    if AUTH_DISABLED_FOR_LOCAL_TESTING:
        return True
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        stamp, signature = decoded.split(b"|", 1)
        expected = hmac.new(SESSION_SECRET, stamp, hashlib.sha256).digest()
        return (hmac.compare_digest(expected, signature)
                and 0 <= time.time() - int(stamp) < SESSION_SECONDS)
    except (ValueError, TypeError, UnicodeDecodeError):
        return False

def load_handover_state():
    try:
        with open(HANDOVER_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def save_handover_state(state):
    try:
        with open(HANDOVER_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError:
        pass

def notify_traveler(sender, text):
    # Best-effort: never raises, since there's no other way to reach an
    # already-open browser tab and a failed note shouldn't fail the resolve.
    try:
        import urllib.request
        from urllib.parse import quote
        payload = json.dumps([{"event": "bot", "text": text}]).encode()
        request = urllib.request.Request(
            f"{RASA_API_URL}/conversations/{quote(sender, safe='')}/tracker/events",
            data=payload, headers={"Content-Type": "application/json"}, method="POST",
        )
        urllib.request.urlopen(request, timeout=5)
    except Exception:
        pass

def delete_session(sender):
    uri = f"file:{DB_PATH.resolve().as_posix()}"
    with sqlite3.connect(uri, uri=True, timeout=5) as connection:
        connection.execute("DELETE FROM events WHERE sender_id = ?", (sender,))
        connection.commit()
    state = load_handover_state()
    if sender in state:
        del state[sender]
        save_handover_state(state)

def delete_all_sessions():
    uri = f"file:{DB_PATH.resolve().as_posix()}"
    with sqlite3.connect(uri, uri=True, timeout=5) as connection:
        connection.execute("DELETE FROM events")
        connection.commit()
    save_handover_state({})

BRIEF_SLOTS = ("destination", "origin", "travel_start", "travel_end", "budget", "currency", "sustainability_level", "transport_preference", "accommodation_preference")
EMPTY_ANALYTICS = {
    "totals": {"conversations": 0, "messages": 0, "user_turns": 0, "plans_generated": 0, "handovers": 0},
    "daily": [], "destinations": [], "transport": [], "currencies": [], "handover_queue": [], "sessions": [], "last_updated": None,
}

def iso(stamp):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp)) if stamp is not None else None

def analytics():
    if not DB_PATH.exists():
        return EMPTY_ANALYTICS
    handover_state = load_handover_state()
    uri = f"file:{DB_PATH.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=3) as connection:
        rows = connection.execute("SELECT sender_id,type_name,timestamp,action_name,data FROM events ORDER BY timestamp").fetchall()
    user_turns, bot_turns, plans, handovers = 0, 0, set(), {}
    days, destinations, transports, currencies = Counter(), Counter(), Counter(), Counter()
    sessions = {}
    latest = None
    for sender, kind, stamp, action, raw in rows:
        if not sender:
            continue
        session = sessions.setdefault(sender, {"last": None, "brief": {}, "plan": False, "handover_at": None, "handover_reason": None})
        if stamp is not None:
            latest = max(latest or stamp, stamp)
            session["last"] = max(session["last"] or stamp, stamp)
            day = time.strftime("%Y-%m-%d", time.gmtime(stamp))
            if kind == "session_started":
                days[day] += 1
        if kind == "user":
            user_turns += 1
        elif kind == "bot":
            bot_turns += 1
        if kind == "action" and action == "action_rank_recommendations":
            plans.add(sender)
            session["plan"] = True
        if kind == "action" and action == "action_human_handover":
            handovers[sender] = stamp
            session["handover_at"] = stamp
        if kind == "slot" and raw:
            try:
                event = json.loads(raw)
                name, value = event.get("name"), event.get("value")
            except (ValueError, AttributeError):
                continue
            if name == "handover_context" and isinstance(value, dict):
                session["handover_reason"] = value.get("reason")
            elif isinstance(value, str) and value.strip():
                if name in BRIEF_SLOTS:
                    session["brief"][name] = value.strip()
                if name == "destination":
                    destinations[value.strip()] += 1
                elif name == "transport_preference":
                    transports[value.strip().title()] += 1
                elif name == "currency":
                    currencies[value.strip().upper()] += 1
    daily = [{"date": key, "conversations": days[key]} for key in sorted(days)[-14:]]
    top = lambda counter: [{"name": key, "count": value} for key, value in counter.most_common(6)]
    # Full sender IDs are included (behind the admin login) so the dashboard
    # can deep-link to the live tracker; this page never stores message text.
    handover_queue = [{
        "sender": sender, "at": iso(stamp), "reason": sessions.get(sender, {}).get("handover_reason") or "requested",
        "resolved": bool(handover_state.get(sender, {}).get("resolved")),
    } for sender, stamp in sorted(handovers.items(), key=lambda item: item[1], reverse=True)[:30]]

    def status_of(session, sender):
        if session["handover_at"]:
            return "Handled" if handover_state.get(sender, {}).get("resolved") else "Escalated"
        if session["plan"]:
            return "Completed"
        if session["brief"]:
            return "In progress"
        return "New"

    def brief_summary(brief):
        dates = f"{brief.get('travel_start', '?')} → {brief.get('travel_end', '?')}" if brief.get("travel_start") else None
        budget = f"{brief.get('currency', 'EUR')} {brief['budget']}" if brief.get("budget") else None
        return {
            "route": f"{brief.get('origin', '?')} → {brief.get('destination', '?')}" if brief.get("origin") or brief.get("destination") else None,
            "dates": dates, "budget": budget, "sustainability": brief.get("sustainability_level"),
        }

    session_rows = sorted(sessions.items(), key=lambda item: item[1]["last"] or 0, reverse=True)[:60]
    # Many sender IDs share a literal prefix ("advisor-<uuid>", "vidhu-...")
    # - truncating from the FRONT made every row's display label (and the
    # frontend's React key) identical, which broke list pagination outright.
    # The trailing segment of a UUID-style ID is effectively random, so it
    # actually distinguishes rows at a glance instead of just repeating.
    session_list = [{
        "sender": f"…{sender[-8:]}", "sender_full": sender, "last_updated": iso(session["last"]), "status": status_of(session, sender),
        "handover_reason": (session["handover_reason"] or "requested") if session["handover_at"] else None,
        "brief": brief_summary(session["brief"]),
    } for sender, session in session_rows]

    return {
        "totals": {"conversations": len(sessions), "messages": user_turns + bot_turns, "user_turns": user_turns, "plans_generated": len(plans), "handovers": len(handovers)},
        "daily": daily, "destinations": top(destinations), "transport": top(transports), "currencies": top(currencies),
        "handover_queue": handover_queue, "sessions": session_list,
        "last_updated": iso(latest),
    }

class Handler(BaseHTTPRequestHandler):
    server_version = "TerraAdmin/1.0"

    def log_message(self, fmt, *args):
        return

    def _send(self, status, payload=None, cookie=None):
        data = b"" if status == 204 else json.dumps(payload or {}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Vary", "Origin")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204)

    def _cookies(self):
        cookies = {}
        for item in self.headers.get("Cookie", "").split(";"):
            if "=" in item:
                key, value = item.strip().split("=", 1)
                cookies[key] = value
        return cookies

    def _authenticated(self):
        return session_is_valid(self._cookies().get("terra_admin", ""))

    def _json_body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0")) or 0))

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/admin/login":
            origin = self.headers.get("Origin", "")
            try:
                body = self._json_body()
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"error": "Invalid request"})
            valid = token_is_valid(str(body.get("token", ""))) if origin in ALLOWED_ORIGINS else False
            if not valid:
                return self._send(401, {"error": "Invalid access token"})
            session = make_session()
            return self._send(200, {"ok": True}, f"terra_admin={session}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}")
        if path == "/api/admin/logout":
            if self.headers.get("Origin", "") not in ALLOWED_ORIGINS:
                return self._send(403, {"error": "Origin not allowed"})
            return self._send(200, {"ok": True}, "terra_admin=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
        if path == "/api/admin/handover/resolve":
            if not self._authenticated():
                return self._send(401, {"error": "Authentication required"})
            try:
                body = self._json_body()
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"error": "Invalid request"})
            sender = str(body.get("sender", "")).strip()
            if not sender:
                return self._send(400, {"error": "Missing sender"})
            resolved = bool(body.get("resolved"))
            note = (str(body.get("note", "")).strip() or None)
            state = load_handover_state()
            state[sender] = {"resolved": resolved, "resolved_at": time.time() if resolved else None, "note": note}
            save_handover_state(state)
            if resolved:
                notify_traveler(sender, note or "A human advisor has reviewed this conversation and it's now marked resolved.")
            return self._send(200, {"ok": True})
        if path == "/api/admin/session/delete":
            if not self._authenticated():
                return self._send(401, {"error": "Authentication required"})
            try:
                body = self._json_body()
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"error": "Invalid request"})
            sender = str(body.get("sender", "")).strip()
            if not sender:
                return self._send(400, {"error": "Missing sender"})
            try:
                delete_session(sender)
            except sqlite3.Error:
                return self._send(503, {"error": "Could not delete - the conversation store is busy, try again"})
            return self._send(200, {"ok": True})
        if path == "/api/admin/sessions/clear":
            if not self._authenticated():
                return self._send(401, {"error": "Authentication required"})
            try:
                body = self._json_body()
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"error": "Invalid request"})
            # Explicit confirm phrase so this irreversible wipe can't be
            # triggered by an accidental or malformed request.
            if str(body.get("confirm", "")) != "DELETE ALL":
                return self._send(400, {"error": "Missing confirmation"})
            try:
                delete_all_sessions()
            except sqlite3.Error:
                return self._send(503, {"error": "Could not clear - the conversation store is busy, try again"})
            return self._send(200, {"ok": True})
        self._send(404, {"error": "Not found"})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/admin/session":
            return self._send(200, {"authenticated": self._authenticated()})
        if path == "/api/admin/analytics":
            if not self._authenticated():
                return self._send(401, {"error": "Authentication required"})
            try:
                return self._send(200, analytics())
            except sqlite3.Error:
                return self._send(503, {"error": "Analytics database is unavailable"})
        self._send(404, {"error": "Not found"})

if __name__ == "__main__":
    if not ADMIN_TOKEN:
        raise SystemExit("No admin access configured. Set ADMIN_TOKEN in .env.")
    print(f"Terra admin analytics listening at http://{ADMIN_HOST}:{ADMIN_PORT}")
    ThreadingHTTPServer((ADMIN_HOST, ADMIN_PORT), Handler).serve_forever()
