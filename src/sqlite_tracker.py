import sqlite3
import logging
from pathlib import Path

class SQLiteTracker:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS downloaded_images (
                file_id TEXT PRIMARY KEY
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sent_events (
                event_id TEXT PRIMARY KEY
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_images (
                image_name TEXT PRIMARY KEY
            )
        ''')
        self.conn.commit()

    def is_image_downloaded(self, file_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT 1 FROM downloaded_images WHERE file_id = ?', (file_id,))
        return cursor.fetchone() is not None

    def mark_image_as_downloaded(self, file_id):
        cursor = self.conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO downloaded_images (file_id) VALUES (?)', (file_id,))
        self.conn.commit()

    def is_event_sent(self, event_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT 1 FROM sent_events WHERE event_id = ?', (event_id,))
        return cursor.fetchone() is not None

    def mark_event_as_sent(self, event_id):
        cursor = self.conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO sent_events (event_id) VALUES (?)', (event_id,))
        self.conn.commit()

    def is_image_processed(self, image_name):
        cursor = self.conn.cursor()
        cursor.execute('SELECT 1 FROM processed_images WHERE image_name = ?', (image_name,))
        return cursor.fetchone() is not None

    def mark_image_as_processed(self, image_name):
        cursor = self.conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO processed_images (image_name) VALUES (?)', (image_name,))
        self.conn.commit()

    def close(self):
        self.conn.close()