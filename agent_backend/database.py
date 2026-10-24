import os
import mysql.connector
from dotenv import load_dotenv
from pathlib import Path

# Load .env from agent_backend directory
load_dotenv(Path(__file__).parent / ".env")


def get_db_connection():
    connection = mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", "ankit"),
        database=os.getenv("DB_NAME", "ai_api_testing")
    )

    return connection