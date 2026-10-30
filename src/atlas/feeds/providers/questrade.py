from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from zoneinfo import ZoneInfo

from ..core import INTERVALS, Capabilities, ProviderAdapter, ProviderError

NY = ZoneInfo("America/New_York")
log = logging.getLogger("atlas.feeds.questrade")

LOGIN_URLS = {"live": "https://login.questrade.com/oauth2/token", "practice": "https://practicelogin.questrade.com/oauth2/token"}
DEFAULT_TOKEN_FILE = Path(__file__).resolve().parents[4] / "var" / "questrade_token.json"   # var/ is gitignored
_LOCK = threading.RLock()   # one refresh at a time: the refresh token is single-use, so two racing refreshes would burn it


def _fp(token: str) -> str:
    """Short one-way fingerprint, used only to tell whether the .env seed changed since the state file was written."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def _ts(s):
    if isinstance(s, (int, float)):
        return float(s)
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


class QuestradeAdapter(ProviderAdapter):
    caps = Capabilities(
        name='questrade', title='Questrade API (market candles)', status="interface_fixture_tested",
        asset_classes=('equity', 'etf', 'option'), schemas=('bars', 'quotes'), intervals=('1m', '5m', '15m', '1h', '1d'),
        history_depth='Candles via /v1/markets/candles/{symbolId}, max 2000 per request',
        live_stream='streaming port via /v1/markets/quotes?stream=true (websocket)',
        rate_limits='Market data: 20 req/s, 15000 req/hour',
        auth_env=('QUESTRADE_REFRESH_TOKEN',),
        official_docs=('https://www.questrade.com/api/documentation/rest-operations/market-calls/markets-candles-id', 'https://www.questrade.com/api/documentation/getting-started', 'https://www.questrade.com/api/documentation/rate-limiting'),
        terms_url='https://www.questrade.com/api/home',
        notes='OAuth refresh-token flow: refresh token -> access_token + api_server (login.questrade.com/oauth2/token). Refresh tokens are single-use and expire after 3 days; ATLAS saves each rotated token atomically to the gitignored var/questrade_token.json (override QUESTRADE_TOKEN_FILE) and prefers it over the .env seed, so a restart keeps working. QUESTRADE_ENV=practice uses practicelogin.questrade.com; the default is the live login (read-only market data; API trading stays disabled). Symbol ids resolved via /v1/symbols/search.')

    # Questrade refresh tokens are single-use. The access token lives in memory only. The rotated refresh token is also saved
    # (atomically, under a lock) to a gitignored state file, so a restart does not fall back to the spent .env seed. Never logged.
    _TOKENS: dict = {}

    def _login_env(self) -> str:
        name = (self.env.get("QUESTRADE_ENV") or "live").strip().lower()
        if name not in LOGIN_URLS:
            raise ProviderError("questrade: QUESTRADE_ENV must be 'live' or 'practice'")
        return name

    def _token_path(self) -> Path:
        return Path(self.env.get("QUESTRADE_TOKEN_FILE") or DEFAULT_TOKEN_FILE)

    @staticmethod
    def _load_saved(path: Path, env_name: str, seed: str):
        """The saved refresh token, or None when the file is missing/invalid, belongs to the other login environment, or was
        written for a different .env seed (a fresh seed from Questrade wins over an older state file)."""
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(d, dict) or d.get("env") != env_name or d.get("seed_fp") != _fp(seed):
            return None
        r = d.get("refresh")
        return r if isinstance(r, str) and r else None

    @staticmethod
    def _save(path: Path, env_name: str, seed: str, refresh: str, now: int) -> bool:
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            with _LOCK:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"version": 1, "env": env_name, "seed_fp": _fp(seed), "refresh": refresh, "saved_at": int(now)}, f)
                    f.flush()
                    os.fsync(f.fileno())
                try:
                    os.chmod(tmp, 0o600)
                except OSError:
                    pass
                os.replace(tmp, path)   # atomic: a reader sees the old file or the new one, never a partial write
            return True
        except OSError as e:
            log.warning("questrade: could not save the rotated refresh token (%s); it is kept in memory only", type(e).__name__)
            try:
                tmp.unlink()
            except OSError:
                pass
            return False

    def _session(self, now):
        seed = self.env["QUESTRADE_REFRESH_TOKEN"]
        env_name, path = self._login_env(), self._token_path()
        key = (env_name, str(path), _fp(seed))
        with _LOCK:
            cur = self._TOKENS.get(key)
            if cur and cur["exp"] > now + 30:
                return cur
            refresh = cur["refresh"] if cur else (self._load_saved(path, env_name, seed) or seed)
            try:
                tok = self.get_json(LOGIN_URLS[env_name], {"grant_type": "refresh_token", "refresh_token": refresh})
            except ProviderError as e:
                msg = str(e)
                for secret in {refresh, seed}:
                    msg = msg.replace(secret, "***")
                self._health.last_error = msg   # core stored the raw body; keep it token-free
                raise ProviderError(msg, e.status, e.retryable, e.geo_blocked) from None
            new_refresh = tok.get("refresh_token") or refresh
            cur = {"access": tok["access_token"], "server": tok["api_server"].rstrip("/"), "refresh": new_refresh,
                   "exp": now + int(tok.get("expires_in", 1800))}
            self._TOKENS[key] = cur
            self._save(path, env_name, seed, new_refresh, now)
            return cur

    def _history(self, instrument, interval, start, end, now):
        cur = self._session(now)
        srv, h = cur["server"], {"Authorization": "Bearer " + cur["access"]}
        sid = self.get_json(f"{srv}/v1/symbols/search", {"prefix": self.provider_symbol(instrument)}, headers=h)["symbols"][0]["symbolId"]
        iso = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).isoformat()
        g = {"1m": "OneMinute", "5m": "FiveMinutes", "15m": "FifteenMinutes", "1h": "OneHour", "1d": "OneDay"}[interval]
        js = self.get_json(f"{srv}/v1/markets/candles/{sid}", {"startTime": iso(start), "endTime": iso(end), "interval": g}, headers=h)
        return [self._bar(instrument, interval, _ts(c["start"]), c["open"], c["high"], c["low"], c["close"], c.get("volume", 0), now) for c in js.get("candles", [])]
