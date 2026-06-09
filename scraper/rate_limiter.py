import random
import time
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, min_delay: float = 2.0, max_delay: float = 4.0):
        self.min_delay = min_delay
        self.max_delay = max_delay

    def wait(self):
        delay = random.uniform(self.min_delay, self.max_delay)
        logger.debug(f"Rate limiter sleeping {delay:.2f}s")
        time.sleep(delay)

    def backoff_wait(self, attempt: int):
        """Exponential backoff: 5s, 10s, 20s for attempts 1, 2, 3."""
        delay = 5 * (2 ** (attempt - 1))
        logger.info(f"Backoff wait {delay}s (attempt {attempt})")
        time.sleep(delay)
