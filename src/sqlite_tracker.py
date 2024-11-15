import logging
import sqlite3
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.connect()
        self.create_tables()
        self.migrate_database()

    def connect(self):
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.cursor = self.conn.cursor()
        except sqlite3.Error as e:
            logger.error(f"Error connecting to database: {e}")
            raise

    @contextmanager
    def transaction(self):
        try:
            yield
            self.conn.commit()
        except sqlite3.Error as e:
            self.conn.rollback()
            logger.error(f"Transaction failed: {e}")
            raise

    def create_tables(self):
        tables = [
            ("processed_images", "image_name TEXT PRIMARY KEY"),
            ("downloaded_images", "image_id TEXT PRIMARY KEY"),
            ("event_titles", "title TEXT PRIMARY KEY"),
            ("events", "id TEXT PRIMARY KEY, summary TEXT, dtstart TEXT, location TEXT"),
            ("sent_events", "event_id TEXT PRIMARY KEY"),
            ("image_hashes", "image_name TEXT PRIMARY KEY, hash TEXT NOT NULL")
        ]

        with self.transaction():
            for table_name, schema in tables:
                self.cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        {schema}
                    )
                """)

    def migrate_database(self):
        try:
            with self.transaction():
                self.cursor.execute("PRAGMA table_info(events)")
                columns = {column[1] for column in self.cursor.fetchall()}

                expected_columns = {"id", "summary", "dtstart", "location"}
                if columns != expected_columns:
                    self.cursor.execute("DROP TABLE IF EXISTS events")
                    self.cursor.execute("""
                        CREATE TABLE events (
                            id TEXT PRIMARY KEY,
                            summary TEXT,
                            dtstart TEXT,
                            location TEXT
                        )
                    """)
                    logger.info("Events table recreated during migration")

            logger.info("Database migration completed successfully")
        except sqlite3.Error as e:
            logger.error(f"Error during database migration: {e}")
            raise

    def add_image_hash(self, image_name, image_hash):
        with self.transaction():
            self.cursor.execute(
                "INSERT OR REPLACE INTO image_hashes (image_name, hash) VALUES (?, ?)",
                (image_name, image_hash)
            )

    def is_hash_processed(self, image_hash):
        try:
            self.cursor.execute(
                "SELECT 1 FROM image_hashes WHERE hash = ? LIMIT 1", (image_hash,)
            )
            return self.cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error checking processed hash: {e}")
            return False

    def mark_image_as_processed(self, image_name):
        with self.transaction():
            self.cursor.execute(
                "INSERT OR REPLACE INTO processed_images (image_name) VALUES (?)",
                (image_name,)
            )

    def is_image_processed(self, image_name):
        try:
            self.cursor.execute(
                "SELECT 1 FROM processed_images WHERE image_name = ? LIMIT 1", (image_name,)
            )
            return self.cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error checking processed image: {e}")
            return False

    def mark_image_as_downloaded(self, image_id):
        with self.transaction():
            self.cursor.execute(
                "INSERT OR REPLACE INTO downloaded_images (image_id) VALUES (?)",
                (image_id,)
            )

    def is_image_downloaded(self, image_id):
        try:
            self.cursor.execute(
                "SELECT 1 FROM downloaded_images WHERE image_id = ? LIMIT 1", (image_id,)
            )
            return self.cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error checking downloaded image: {e}")
            return False

    def add_event_title(self, title):
        with self.transaction():
            self.cursor.execute(
                "INSERT OR IGNORE INTO event_titles (title) VALUES (?)", (title,)
            )

    def is_duplicate_event(self, event_data):
        try:
            event_id = f"{event_data['SUMMARY']}_{event_data['DTSTART']}_{event_data['LOCATION']}"
            self.cursor.execute("SELECT 1 FROM events WHERE id = ? LIMIT 1", (event_id,))
            return self.cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error checking duplicate event: {e}")
            return False

    def add_event(self, event_data):
        try:
            event_id = f"{event_data['SUMMARY']}_{event_data['DTSTART']}_{event_data['LOCATION']}"
            with self.transaction():
                self.cursor.execute(
                    "INSERT OR REPLACE INTO events (id, summary, dtstart, location) VALUES (?, ?, ?, ?)",
                    (event_id, event_data['SUMMARY'], str(event_data['DTSTART']), event_data['LOCATION'])
                )
            logger.info(f"Event added to database: {event_id}")
        except sqlite3.Error as e:
            logger.error(f"Error adding event to database: {e}")

    def mark_event_as_sent(self, event_id):
        with self.transaction():
            self.cursor.execute(
                "INSERT OR REPLACE INTO sent_events (event_id) VALUES (?)", (event_id,)
            )

    def is_event_sent(self, event_id):
        try:
            self.cursor.execute(
                "SELECT 1 FROM sent_events WHERE event_id = ? LIMIT 1", (event_id,)
            )
            return self.cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error checking sent event: {e}")
            return False

    def close(self):
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()