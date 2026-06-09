import requests
from bs4 import BeautifulSoup
from config import BASE_URL, REQUEST_HEADERS, SESSION_REFRESH_INTERVAL
import logging

logger = logging.getLogger(__name__)


class PlateSession:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(REQUEST_HEADERS)
        self._tokens: dict = {}
        self._batch_count = 0

    def get_tokens(self) -> dict:
        """GET the form page and extract ASP.NET hidden field tokens."""
        try:
            resp = self.session.get(BASE_URL, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch form page: {e}")
            raise

        soup = BeautifulSoup(resp.text, "lxml")

        def _val(name: str) -> str:
            tag = soup.find("input", {"name": name})
            return tag["value"] if tag else ""

        self._tokens = {
            "__VIEWSTATE": _val("__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": _val("__VIEWSTATEGENERATOR"),
            "__EVENTVALIDATION": _val("__EVENTVALIDATION"),
        }

        if not self._tokens["__VIEWSTATE"]:
            logger.warning("__VIEWSTATE token is empty — the page structure may have changed")

        return self._tokens

    def refresh_if_needed(self) -> dict:
        """Refresh tokens on first call or every SESSION_REFRESH_INTERVAL batches."""
        if self._batch_count % SESSION_REFRESH_INTERVAL == 0 or not self._tokens:
            self.get_tokens()
        self._batch_count += 1
        return self._tokens

    def force_refresh(self) -> dict:
        """Force a full session + token refresh (call after errors)."""
        self._batch_count = 0
        self._tokens = {}
        # Reset session cookies to start fresh
        self.session.cookies.clear()
        return self.get_tokens()
