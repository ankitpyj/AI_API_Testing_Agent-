
import os
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def get_db_connection():
    required_vars = ["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"]

    missing = [name for name in required_vars if not os.getenv(name)]

    if missing:
        raise RuntimeError(
            "Missing database environment variables: "
            + ", ".join(missing)
        )

    return mysql.connector.connect(
        ssl_ca=os.getenv(
            "DB_SSL_CA",
            str(Path(__file__).parent / "ca.pem")
            ),
        ssl_verify_cert=True,
        ssl_verify_identity=True,
        host=os.environ["DB_HOST"],
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        connection_timeout=10
    )