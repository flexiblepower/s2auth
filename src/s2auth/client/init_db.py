import os
import sqlite3

# Single, shared SQLite DB path (same as used in client.main)
DB_PATH = os.path.join(os.path.dirname(__file__), "connection_details.db")
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS connection_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    s2_node_id TEXT NOT NULL,
    auth_token TEXT NOT NULL
)
""")

conn.commit()
conn.close()
