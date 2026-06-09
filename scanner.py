import threading
import time
import uuid
import logging
from datetime import datetime, timezone

from config import BATCH_SIZE, WORDLIST_PATH
from scraper.session import PlateSession
from scraper.checker import check_batch
from scraper.rate_limiter import RateLimiter
from storage import queries
from storage.database import init_db
from generator.combinations import numeric_range_plates, alpha_plates, word_plates
from generator.patterns import pattern_plates

logger = logging.getLogger(__name__)


class SearchTask:
    def __init__(self):
        self.thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stats_lock = threading.Lock()
        self._rate_limiter = RateLimiter()
        self.stats = {
            "checked": 0,
            "available": 0,
            "unavailable": 0,
            "errors": 0,
            "current_plate": "",
            "started_at": None,
            "rate": 0.0,
            "recent_found": [],
        }
        self.running = False
        self.session_id: str | None = None

    def _reset_stats(self):
        with self._stats_lock:
            self.stats = {
                "checked": 0,
                "available": 0,
                "unavailable": 0,
                "errors": 0,
                "current_plate": "",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "rate": 0.0,
                "recent_found": [],
            }

    def get_status(self) -> dict:
        with self._stats_lock:
            return {**self.stats, "running": self.running}

    def update_delays(self, min_delay: float, max_delay: float):
        self._rate_limiter.min_delay = max(0.5, min_delay)
        self._rate_limiter.max_delay = max(self._rate_limiter.min_delay, max_delay)

    def start(self, config: dict):
        if self.running:
            return {"error": "Search already running"}

        init_db()
        self.session_id = str(uuid.uuid4())[:8]
        queries.create_session(self.session_id, config)

        min_delay = float(config.get("min_delay", 2.0))
        max_delay = float(config.get("max_delay", 4.0))
        self._rate_limiter = RateLimiter(min_delay, max_delay)

        self._stop_event.clear()
        self._reset_stats()
        self.running = True

        self.thread = threading.Thread(target=self._worker, args=(config,), daemon=True)
        self.thread.start()
        return {"session_id": self.session_id}

    def stop(self):
        self._stop_event.set()
        self.running = False

    def _build_generators(self, config: dict):
        gens = []
        if config.get("numeric"):
            min_d = int(config.get("numeric_min_len", 1))
            max_d = int(config.get("numeric_max_len", 3))
            gens.append(("numeric", numeric_range_plates(min_d, max_d)))
        if config.get("alpha"):
            min_a = int(config.get("alpha_min_len", 1))
            max_a = int(config.get("alpha_max_len", 3))
            gens.append(("alpha", alpha_plates(min_a, max_a)))
        if config.get("words"):
            min_w = int(config.get("words_min_len", 3))
            max_w = int(config.get("words_max_len", 4))
            gens.append(("word", word_plates(WORDLIST_PATH, min_w, max_w)))
        if config.get("pattern") and config.get("pattern_string"):
            gens.append(("pattern", pattern_plates(config["pattern_string"].strip())))
        return gens

    def _worker(self, config: dict):
        plate_session = PlateSession()
        try:
            plate_session.get_tokens()
        except Exception as e:
            logger.error(f"Could not initialize session: {e}")
            self.running = False
            return

        typed_generators = self._build_generators(config)
        if not typed_generators:
            logger.warning("No generators configured")
            self.running = False
            return

        def all_plates():
            for ptype, gen in typed_generators:
                for plate in gen:
                    yield ptype, plate

        batch_plates: list[str] = []
        batch_types: list[str] = []
        start_time = time.monotonic()

        for ptype, plate in all_plates():
            if self._stop_event.is_set():
                break
            batch_plates.append(plate)
            batch_types.append(ptype)
            if len(batch_plates) < BATCH_SIZE:
                continue
            self._process_batch(batch_plates, batch_types, plate_session, start_time)
            batch_plates = []
            batch_types = []

        if batch_plates and not self._stop_event.is_set():
            self._process_batch(batch_plates, batch_types, plate_session, start_time)

        with self._stats_lock:
            checked = self.stats["checked"]
            available = self.stats["available"]

        queries.close_session(self.session_id, checked, available)
        self.running = False
        logger.info(f"Search finished. Checked={checked}, Available={available}")

    def _process_batch(self, plates, plate_types, plate_session, start_time):
        unchecked = queries.get_unchecked_plates(plates)
        if not unchecked:
            return

        type_map = dict(zip(plates, plate_types))

        with self._stats_lock:
            self.stats["current_plate"] = unchecked[0]

        results = check_batch(
            unchecked,
            plate_session,
            self._rate_limiter,
            session_id=self.session_id,
            plate_type=type_map.get(unchecked[0], "unknown"),
        )

        for r in results:
            r["plate_type"] = type_map.get(r["plate"], "unknown")

        queries.insert_results(results)

        with self._stats_lock:
            for r in results:
                self.stats["checked"] += 1
                if r["status"] == "AVAILABLE":
                    self.stats["available"] += 1
                    self.stats["recent_found"] = ([r["plate"]] + self.stats["recent_found"])[:12]
                    logger.info(f"AVAILABLE: {r['plate']}")
                elif r["status"] == "UNAVAILABLE":
                    self.stats["unavailable"] += 1
                else:
                    self.stats["errors"] += 1

            elapsed = time.monotonic() - start_time
            if elapsed > 0:
                self.stats["rate"] = round(self.stats["checked"] / elapsed * 60, 1)

        self._rate_limiter.wait()
