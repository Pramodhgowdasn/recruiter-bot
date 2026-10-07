"""Load the Part 2 dataset into an in-memory SQLite DB and print every answer.

    python sql/run_detective.py
"""

import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

conn = sqlite3.connect(":memory:")
conn.executescript((ROOT / "sql" / "hiring_ops_setup.sql").read_text())

# Split sql_detective.sql on its "-- Question N ----" banners, one query per chunk.
chunks = re.split(r"^-- (Question .+?) -+$", (ROOT / "sql_detective.sql").read_text(), flags=re.M)
for title, body in zip(chunks[1::2], chunks[2::2]):
    cursor = conn.execute(body.strip())
    columns = [d[0] for d in cursor.description]
    print(f"\n== {title} ==")
    print(" | ".join(columns))
    for row in cursor:
        print(" | ".join(str(v) for v in row))
