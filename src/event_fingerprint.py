import hashlib
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class EventFingerprint:
    def __init__(self, summary, date, location, description):
        self.summary = self._normalize_text(summary)
        self.date = self._normalize_date(date)
        self.location = self._normalize_text(location)
        self.description = self._normalize_text(description)

    def _normalize_text(self, text):
        if text is None:
            return ""
        return " ".join(str(text).lower().split())

    def _normalize_date(self, date):
        if isinstance(date, str):
            try:
                # Intenta con el formato '%Y%m%dT%H%M%S'
                return datetime.strptime(date, "%Y%m%dT%H%M%S").strftime("%Y-%m-%d")
            except ValueError:
                try:
                    # Si falla, intenta con el formato '%Y%m%dT%H%M'
                    return datetime.strptime(date, "%Y%m%dT%H%M").strftime("%Y-%m-%d")
                except ValueError:
                    try:
                        # Si falla, intenta con el formato '%Y-%m-%d'
                        return datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d")
                    except ValueError:
                        # Si todos fallan, registra un error y devuelve la fecha como está
                        print(f"Warning: Unable to parse date {date}. Using as is.")
                        return date
        elif isinstance(date, datetime):
            return date.strftime("%Y-%m-%d")
        else:
            return str(date)

    def generate(self):
        fingerprint = (
            f"{self.summary}|{self.date}|{self.location}|{self.description[:100]}"
        )
        return hashlib.md5(fingerprint.encode()).hexdigest()

    def is_similar(self, other_fingerprint, threshold=0.8):
        return self._similarity(self.generate(), other_fingerprint) >= threshold

    def _similarity(self, fp1, fp2):
        return sum(c1 == c2 for c1, c2 in zip(fp1, fp2)) / len(fp1)
