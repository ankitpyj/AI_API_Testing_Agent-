"""
Migration 011 Runner: Idempotently apply background job lifecycle fields to MySQL.
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
        print(f"Existing columns count: {len(existing_cols)}")

        # 2. Add columns if not already present
        if "created_at" not in existing_cols:
            print("Adding created_at column...")
            cur.execute(
                "ALTER TABLE test_runs ADD COLUMN created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP AFTER project_id"
            )

        if "completed_at" not in existing_cols:
            print("Adding completed_at column...")
            cur.execute(
                "ALTER TABLE test_runs ADD COLUMN completed_at TIMESTAMP NULL DEFAULT NULL AFTER started_at"
            )

        if "base_url" not in existing_cols:
            print("Adding base_url column...")
            cur.execute(
                "ALTER TABLE test_runs ADD COLUMN base_url VARCHAR(255) NULL AFTER completed_at"
            )

        if "openapi_url" not in existing_cols:
            print("Adding openapi_url column...")
            cur.execute(
                "ALTER TABLE test_runs ADD COLUMN openapi_url VARCHAR(255) NULL AFTER base_url"
            )

        if "error_message" not in existing_cols:
            print("Adding error_message column...")
            cur.execute(
                "ALTER TABLE test_runs ADD COLUMN error_message TEXT NULL AFTER failed_tests"
            )

        if "worker_id" not in existing_cols:
            print("Adding worker_id column...")
            cur.execute(
                "ALTER TABLE test_runs ADD COLUMN worker_id VARCHAR(64) NULL AFTER reservation_expires_at"
            )

        # 3. Backfill created_at and completed_at for historical records
        print("Backfilling historical timestamps...")
        cur.execute(
            """
            UPDATE test_runs
            SET created_at = started_at
            WHERE created_at IS NULL AND started_at IS NOT NULL
            """
        )

        cur.execute(
            """
            UPDATE test_runs
            SET completed_at = heartbeat_at
            WHERE status = 'completed' AND completed_at IS NULL AND heartbeat_at IS NOT NULL
            """
        )

        # 4. Modify started_at to allow NULL for newly queued jobs
        print("Modifying started_at to allow NULL for queued jobs...")
        cur.execute(
            "ALTER TABLE test_runs MODIFY COLUMN started_at TIMESTAMP NULL DEFAULT NULL"
        )

        # 5. Check and create queue claiming index
        cur.execute(
            """
            SELECT INDEX_NAME
            FROM information_schema.STATISTICS
            WHERE TABLE_NAME = 'test_runs'
            """
        )
        existing_indexes = {r["INDEX_NAME"].lower() for r in cur.fetchall()}

        if "idx_test_runs_queue_claim" not in existing_indexes:
            print("Creating idx_test_runs_queue_claim index...")
            cur.execute(
                "CREATE INDEX idx_test_runs_queue_claim ON test_runs (status, created_at, id)"
            )

        conn.commit()
        print("Migration 011 successfully applied and committed!")
        return True
    except Exception as e:
        conn.rollback()
        print(f"Migration 011 failed: {e}")
        raise e
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    apply_migration()
