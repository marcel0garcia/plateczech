import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

from config import (
    BASE_URL,
    PLATE_INPUT_FIELDS,
    PLATE_RESULT_IDS,
    MAX_RETRIES,
)
from scraper.session import PlateSession
from scraper.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


def _normalize_status(text: str) -> str:
    """Convert raw result span text to a clean status string."""
    if not text:
        return "ERROR"
    t = text.strip().upper()
    if "NOT AVAILABLE" in t or "UNAVAILABLE" in t:
        return "UNAVAILABLE"
    if "AVAILABLE" in t:
        return "AVAILABLE"
    if "INVALID" in t or "NOT VALID" in t:
        return "INVALID"
    return "ERROR"


def check_batch(
    plates: list[str],
    plate_session: PlateSession,
    rate_limiter: RateLimiter,
    session_id: str = None,
    plate_type: str = None,
) -> list[dict]:
    """
    Check availability for up to 5 plates in a single POST request.
    Returns a list of result dicts: {plate, status, plate_type, checked_at, session_id}
    """
    plates = [p.upper()[:7] for p in plates[:5]]

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            tokens = plate_session.refresh_if_needed()

            # Build POST payload
            payload = {
                "__VIEWSTATE": tokens.get("__VIEWSTATE", ""),
                "__VIEWSTATEGENERATOR": tokens.get("__VIEWSTATEGENERATOR", ""),
                "__EVENTVALIDATION": tokens.get("__EVENTVALIDATION", ""),
                "ctl00$MainContent$btnSubmit": "Submit",
            }
            # Fill plate fields; empty string for unused slots
            for i, field in enumerate(PLATE_INPUT_FIELDS):
                payload[field] = plates[i] if i < len(plates) else ""

            resp = plate_session.session.post(BASE_URL, data=payload, timeout=20)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "lxml")
            results = []
            now = datetime.now(timezone.utc).isoformat()

            for i, plate in enumerate(plates):
                span = soup.find(id=PLATE_RESULT_IDS[i])
                # Fallback: try alternate capitalization for row 5
                if span is None and i == 4:
                    span = soup.find(id="MainContent_lblOutPutRowFive")
                raw_text = span.get_text(strip=True) if span else ""
                status = _normalize_status(raw_text)
                results.append({
                    "plate": plate,
                    "status": status,
                    "plate_type": plate_type,
                    "checked_at": now,
                    "session_id": session_id,
                    "raw_response": raw_text,
                })
                logger.debug(f"{plate}: {status} ({raw_text!r})")

            return results

        except requests.HTTPError as e:
            logger.warning(f"HTTP error on attempt {attempt}: {e}")
            if e.response is not None and e.response.status_code == 429:
                rate_limiter.backoff_wait(attempt)
            elif attempt < MAX_RETRIES:
                plate_session.force_refresh()
                rate_limiter.backoff_wait(attempt)
            else:
                break

        except requests.RequestException as e:
            logger.warning(f"Request error on attempt {attempt}: {e}")
            if attempt < MAX_RETRIES:
                rate_limiter.backoff_wait(attempt)
            else:
                break

    # All retries exhausted — return ERROR for all plates
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "plate": p,
            "status": "ERROR",
            "plate_type": plate_type,
            "checked_at": now,
            "session_id": session_id,
            "raw_response": "",
        }
        for p in plates
    ]
