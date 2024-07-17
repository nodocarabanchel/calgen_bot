import sqlite3
from event_fingerprint import EventFingerprint

class DatabaseManager:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS processed_images (
            image_name TEXT PRIMARY KEY
        )
        ''')
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS sent_events (
            event_id TEXT PRIMARY KEY
        )
        ''')
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS event_titles (
            title TEXT PRIMARY KEY
        )
        ''')
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            fingerprint TEXT PRIMARY KEY,
            title TEXT,
            date TEXT,
            location TEXT,
            description TEXT
        )
        ''')
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS image_hashes (
            image_name TEXT PRIMARY KEY,
            hash TEXT
        )
        ''')

    def add_image_hash(self, image_name, image_hash):
        self.cursor.execute('INSERT OR REPLACE INTO image_hashes (image_name, hash) VALUES (?, ?)', (image_name, image_hash))
        self.conn.commit()

    def get_image_hash(self, image_name):
        self.cursor.execute('SELECT hash FROM image_hashes WHERE image_name = ?', (image_name,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def is_hash_processed(self, image_hash):
        self.cursor.execute('SELECT 1 FROM image_hashes WHERE hash = ?', (image_hash,))
        return self.cursor.fetchone() is not None

    def is_image_downloaded(self, image_name):
        return self.is_image_processed(image_name)

    def is_image_processed(self, image_name):
        self.cursor.execute('SELECT 1 FROM processed_images WHERE image_name = ?', (image_name,))
        return self.cursor.fetchone() is not None

    def mark_image_as_downloaded(self, image_name):
        return self.mark_image_as_processed(image_name)

    def mark_image_as_processed(self, image_name):
        self.cursor.execute('INSERT OR IGNORE INTO processed_images (image_name) VALUES (?)', (image_name,))
        self.conn.commit()

    def is_event_sent(self, event_id):
        self.cursor.execute('SELECT 1 FROM sent_events WHERE event_id = ?', (event_id,))
        return self.cursor.fetchone() is not None

    def mark_event_as_sent(self, event_id):
        self.cursor.execute('INSERT OR IGNORE INTO sent_events (event_id) VALUES (?)', (event_id,))
        self.conn.commit()

    def add_event_title(self, title):
        self.cursor.execute('INSERT OR IGNORE INTO event_titles (title) VALUES (?)', (title,))
        self.conn.commit()

    def is_duplicate_event(self, event):
        fingerprint = EventFingerprint(
            event['summary'],
            event['dtstart'],
            event['location'],
            event.get('description', '')
        )
        fp_hash = fingerprint.generate()

        self.cursor.execute("SELECT fingerprint FROM events WHERE fingerprint = ?", (fp_hash,))
        if self.cursor.fetchone():
            return True

        self.cursor.execute("SELECT fingerprint FROM events")
        for (stored_fp,) in self.cursor.fetchall():
            if fingerprint.is_similar(stored_fp):
                return True

        return False

    def add_event(self, event):
        fingerprint = EventFingerprint(
            event['summary'],
            event['dtstart'],
            event['location'],
            event.get('description', '')
        )
        fp_hash = fingerprint.generate()

        self.cursor.execute('''
        INSERT OR REPLACE INTO events (fingerprint, title, date, location, description)
        VALUES (?, ?, ?, ?, ?)
        ''', (fp_hash, event['summary'], event['dtstart'], event['location'], event.get('description', '')))
        self.conn.commit()

    def close(self):
        self.conn.close()