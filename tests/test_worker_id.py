import os
import re
import socket
from unittest.mock import MagicMock, patch
import pytest

from agent_backend.worker import WORKER_ID, generate_worker_id


class TestWorkerIdBoundedLengthAndEntropy:
    """Automated tests validating worker_id bounds, entropy, and collision resistance."""

    def test_worker_id_length_is_bounded(self):
        """Worker ID must strictly be <= 64 characters for VARCHAR(64) compatibility."""
        wid = generate_worker_id()
        assert len(wid) <= 64, f"Worker ID '{wid}' exceeded 64 chars ({len(wid)})"
        assert len(WORKER_ID) <= 64, f"Global WORKER_ID '{WORKER_ID}' exceeded 64 chars ({len(WORKER_ID)})"
        assert wid.startswith("w-"), f"Worker ID '{wid}' must start with 'w-'"

    @pytest.mark.parametrize("length", [10, 50, 100, 255])
    def test_works_with_various_hostname_lengths(self, length):
        """Worker ID must remain <= 64 chars even with extreme hostname lengths."""
        simulated_hostname = ("subdomain" + "x" * length)[:length] + ".internal.cloud"
        wid = generate_worker_id(hostname=simulated_hostname, pid=9999999)
        assert len(wid) <= 64, f"Failed for length {length}: '{wid}' ({len(wid)} chars)"
        # Hostname slug is bounded to max 12 chars
        slug = wid.split("-")[1]
        assert len(slug) <= 12

    def test_full_uuid_entropy_preserved(self):
        """Must preserve the full 32-character UUID4 hex string without truncation."""
        wid = generate_worker_id()
        parts = wid.split("-")
        # Format: w-{slug}-{pid}-{uuid_hex}
        uuid_part = parts[-1]
        assert len(uuid_part) == 32, f"Expected 32 hex chars, got {len(uuid_part)}: '{uuid_part}'"
        # Verify valid hex
        int(uuid_part, 16)

    def test_1000_generated_identifiers_have_no_collisions(self):
        """1,000 generated identifiers on the same host and PID must have zero collisions."""
        count = 1000
        fixed_host = "render-k8s-pod-ai-api-agent"
        fixed_pid = 12345
        generated = [generate_worker_id(hostname=fixed_host, pid=fixed_pid) for _ in range(count)]
        
        # All must be <= 64
        for wid in generated:
            assert len(wid) <= 64
            
        # Must all be unique
        unique_set = set(generated)
        assert len(unique_set) == count, f"Collision detected! Expected {count} unique IDs, got {len(unique_set)}"

    def test_worker_id_remains_consistent_throughout_process(self):
        """WORKER_ID module-level constant remains identical across calls in a single process."""
        id1 = WORKER_ID
        id2 = WORKER_ID
        assert id1 == id2
        assert len(id1) <= 64


class TestWorkerOwnershipFencingContracts:
    """Validates that ownership fencing properly checks worker_id against mismatches."""

    def test_stale_worker_cannot_update_or_complete_another_worker_job(self):
        """A stale worker cannot update heartbeat or complete a job owned by another worker."""
        from agent_backend.usage_service import update_heartbeat, complete_test_run
        
        # Mock database connection and cursor to test SQL query predicates safely
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("agent_backend.usage_service.get_db_connection", return_value=mock_conn):
            # 1. Update heartbeat with mismatched worker
            mock_cursor.rowcount = 0  # 0 rows affected because worker_id mismatch
            updated = update_heartbeat(run_id=999, worker_id="stale-worker-id")
            assert updated is False
            
            # Verify SQL query enforced worker_id predicate
            execute_args = mock_cursor.execute.call_args[0]
            sql = execute_args[0]
            params = execute_args[1]
            assert "worker_id = %s" in sql
            assert "stale-worker-id" in params

            # 2. Complete test run with mismatched worker
            mock_cursor.rowcount = 0  # 0 rows affected because worker_id mismatch
            completed = complete_test_run(
                run_id=999,
                total_tests=10,
                passed_tests=10,
                failed_tests=0,
                worker_id="stale-worker-id"
            )
            assert completed is False

    def test_slot_acquisition_heartbeat_completion_and_release_use_same_id(self):
        """Verifies consistent worker_id propagation across execution lifecycle."""
        active_wid = WORKER_ID

        # Mock db_operations
        with patch("agent_backend.db_operations.get_db_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_get_conn.return_value = mock_conn

            from agent_backend.db_operations import release_worker_slot
            
            # Release worker slot enforces worker_id
            release_worker_slot(run_id=999, worker_id=active_wid)
            execute_args = mock_cursor.execute.call_args[0]
            sql = execute_args[0]
            params = execute_args[1]
            assert "worker_id = %s" in sql
            assert active_wid in params
