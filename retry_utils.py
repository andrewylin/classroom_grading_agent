import logging
import time

from googleapiclient.errors import HttpError

log = logging.getLogger("retry_utils")


def retry_on_transient_error(action, description: str, max_retries: int = 4):
    for attempt in range(max_retries):
        try:
            return action()
        except (OSError, TimeoutError, ConnectionError, HttpError) as exc:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt
            log.warning(
                "Transient Google API error for %s (attempt %d/%d): %s; retrying in %s seconds",
                description,
                attempt + 1,
                max_retries,
                exc,
                wait,
            )
            time.sleep(wait)
