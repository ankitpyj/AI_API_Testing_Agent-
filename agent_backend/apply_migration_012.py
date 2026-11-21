"""
Migration 012 Runner: Idempotently apply worker_slots table and payload_hash column to MySQL.
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.resolve()
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from database import get_db_connection


def apply_migration():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    try:
        # 1. Discover existing columns in test_runs
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_NAME = 'test_runs'
            """
        )
        existing_cols = {r["COLUMN_NAME"].lower() for r in cur.fetchall()}

        if "payload_hash" not in existing_cols:
            print("Adding payload_hash column to test_runs...")
            cur.execute(
                "ALTER TABLE test_runs ADD COLUMN payload_hash VARCHAR(64) NULL AFTER idempotency_key"
            )

        # 2. Check and create worker_slots table
        cur.execute(
            """
            SELECT TABLE_NAME
            FROM information_schema.TABLES
            WHERE TABLE_NAME = 'worker_slots'
            """
        )
        tables = [r["TABLE_NAME"].lower() for r in cur.fetchall()]

        if "worker_slots" not in tables:
            print("Creating worker_slots table...")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_slots (
                    slot_id INT NOT NULL PRIMARY KEY,
                    run_id INT NULL UNIQUE,
                    worker_id VARCHAR(64) NULL,
                    leased_until TIMESTAMP NULL,
                    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_worker_slots_lease (leased_until),
                    FOREIGN KEY (run_id) REFERENCES test_runs(id) ON DELETE SET NULL
                ) ENGINE=InnoDB
                """
            )

        # 3. Pre-seed worker slots 1 through 20
        print("Seeding worker_slots 1 through 20...")
        slot_values = ", ".join(f"({i})" for i in range(1, 21))
        cur.execute(f"INSERT IGNORE INTO worker_slots (slot_id) VALUES {slot_values}")

        conn.commit()
        print("Migration 012 successfully applied and committed!")
        return True
    except Exception as e:
        conn.rollback()
        print(f"Migration 012 failed: {e}")
        raise e
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    apply_migration()
