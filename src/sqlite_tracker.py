import json
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
            ("image_hashes", """
                image_name TEXT PRIMARY KEY, 
                hash TEXT NOT NULL,
                similarity_info TEXT,
                processed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            """)
        ]

        with self.transaction():
            for table_name, schema in tables:
                self.cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        {schema}
                    )
                """)

    # Añadir este nuevo método:
    def migrate_database(self):
        try:
            with self.transaction():
                # Verificar columnas actuales
                self.cursor.execute("PRAGMA table_info(image_hashes)")
                columns = {column[1] for column in self.cursor.fetchall()}
                
                # Migrar si es necesario
                if 'hash_info' not in columns:
                    self.cursor.execute("""
                        CREATE TABLE image_hashes_new (
                            image_name TEXT PRIMARY KEY,
                            phash TEXT NOT NULL,
                            hash_info TEXT,
                            processed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    
                    # Migrar datos existentes
                    self.cursor.execute("""
                        INSERT INTO image_hashes_new (image_name, phash)
                        SELECT image_name, hash FROM image_hashes
                    """)
                    
                    self.cursor.execute("DROP TABLE image_hashes")
                    self.cursor.execute("ALTER TABLE image_hashes_new RENAME TO image_hashes")
        except sqlite3.Error as e:
            logger.error(f"Error en migración: {e}")
            raise

    def add_image_hash(self, image_name, image_hash):
        with self.transaction():
            self.cursor.execute(
                "INSERT OR REPLACE INTO image_hashes (image_name, hash) VALUES (?, ?)",
                (image_name, image_hash)
            )

    def add_image_hash_with_info(self, image_name, phash, hash_info):
        query = """INSERT OR REPLACE INTO image_hashes 
                (image_name, phash, hash_info) VALUES (?, ?, ?)"""
        self.execute(query, (image_name, phash, json.dumps(hash_info)))

    def is_hash_processed(self, phash):
        try:
            self.cursor.execute(
                "SELECT 1 FROM image_hashes WHERE phash = ? LIMIT 1",
                (phash,)
            )
            return self.cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error verificando hash: {e}")
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