import os
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

# Load env
load_dotenv();

# Get the env of DB & fail loud if not present
DATABASE_URL= os.environ["DATABASE_URL"]

def run_query(sql: str, params: tuple = ()) -> list[dict]:
    """Run one parameterized, read-only query and return rows as dicts."""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
