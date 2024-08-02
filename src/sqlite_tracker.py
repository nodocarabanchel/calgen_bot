import sqlite3
import logging
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self.create_tables()
        self.migrate_database()

    def create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_images (
                image_name TEXT PRIMARY KEY
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS downloaded_images (
                image_id TEXT PRIMARY KEY
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS event_titles (
                title TEXT PRIMARY KEY
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                summary TEXT,
                dtstart TEXT,
                location TEXT
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS sent_events (
                event_id TEXT PRIMARY KEY
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS image_hashes (
                image_name TEXT PRIMARY KEY,
                hash TEXT NOT NULL
            )
        ''')
        self.conn.commit()

    def migrate_database(self):
        try:
            # Verificar si las columnas existen
            self.cursor.execute("PRAGMA table_info(events)")
            columns = [column[1] for column in self.cursor.fetchall()]

            # Si la tabla está vacía o no tiene las columnas correctas, recréala
            if not columns or set(columns) != {'id', 'summary', 'dtstart', 'location'}:
                self.cursor.execute("DROP TABLE IF EXISTS events")
                self.cursor.execute('''
                    CREATE TABLE events (
                        id TEXT PRIMARY KEY,
                        summary TEXT,
                        dtstart TEXT,
                        location TEXT
                    )
                ''')

            self.conn.commit()
            logger.info("Database migration completed successfully")
        except sqlite3.Error as e:
            logger.error(f"Error during database migration: {e}")
            self.conn.rollback()

    def add_image_hash(self, image_name, image_hash):
        try:
            self.cursor.execute("INSERT OR REPLACE INTO image_hashes (image_name, hash) VALUES (?, ?)",
                                (image_name, image_hash))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error adding image hash: {e}")

    def is_hash_processed(self, image_hash):
        try:
            self.cursor.execute(
                "SELECT * FROM image_hashes WHERE hash = ?", (image_hash,))
            return self.cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error checking processed hash: {e}")
            return False

    def mark_image_as_processed(self, image_name):
        try:
            self.cursor.execute(
                "INSERT OR REPLACE INTO processed_images (image_name) VALUES (?)", (image_name,))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error marking image as processed: {e}")

    def is_image_processed(self, image_name):
        try:
            self.cursor.execute(
                "SELECT * FROM processed_images WHERE image_name = ?", (image_name,))
            return self.cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error checking processed image: {e}")
            return False

    def mark_image_as_downloaded(self, image_id):
        try:
            self.cursor.execute(
                "INSERT OR REPLACE INTO downloaded_images (image_id) VALUES (?)", (image_id,))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error marking image as downloaded: {e}")

    def is_image_downloaded(self, image_id):
        try:
            self.cursor.execute(
                "SELECT * FROM downloaded_images WHERE image_id = ?", (image_id,))
            return self.cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error checking downloaded image: {e}")
            return False

    def add_event_title(self, title):
        try:
            self.cursor.execute(
                "INSERT OR IGNORE INTO event_titles (title) VALUES (?)", (title,))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error adding event title: {e}")

    def is_duplicate_event(self, event_data):
        try:
            self.cursor.execute("SELECT * FROM events WHERE summary = ? AND dtstart = ? AND location = ?",
                                (event_data.get('summary'), event_data.get('dtstart'), event_data.get('location')))
            return self.cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error checking duplicate event: {e}")
            return False

    def add_event(self, event_data):
        try:
            event_id = f"{event_data.get('summary')}_{event_data.get('dtstart')}_{event_data.get('location')}"
            self.cursor.execute("INSERT OR REPLACE INTO events (id, summary, dtstart, location) VALUES (?, ?, ?, ?)",
                                (event_id, event_data.get('summary'), event_data.get('dtstart'), event_data.get('location')))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error adding event: {e}")

    def mark_event_as_sent(self, event_id):
        try:
            self.cursor.execute(
                "INSERT OR REPLACE INTO sent_events (event_id) VALUES (?)", (event_id,))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error marking event as sent: {e}")

    def is_event_sent(self, event_id):
        try:
            self.cursor.execute(
                "SELECT * FROM sent_events WHERE event_id = ?", (event_id,))
            return self.cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error checking sent event: {e}")
            return False

    def close(self):
        self.conn.close()
