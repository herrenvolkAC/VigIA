from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from routers import rrhh_novedades


class OracleSchedulerCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "rrhh.db"
        self.original_db_path = rrhh_novedades.DB_PATH
        rrhh_novedades.DB_PATH = self.db_path
        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    """CREATE TABLE rrhh_import_batches (
                        batch_id INTEGER PRIMARY KEY, batch_key TEXT, source_dir TEXT,
                        imported_by TEXT, status TEXT, files_json TEXT
                    )"""
                )
                conn.execute(
                    "CREATE TABLE rrhh_actividad_diaria (batch_id INTEGER, fecha TEXT, origen_dato TEXT)"
                )

    def tearDown(self) -> None:
        rrhh_novedades.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_completed_batch_is_checkpoint_even_without_activity_rows(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn:
                conn.executemany(
                    "INSERT INTO rrhh_import_batches (batch_key, status) VALUES (?, ?)",
                    [
                        ("oracle_actividad_20261006", "complete"),
                        ("oracle_actividad_20261007", "running"),
                    ],
                )

        self.assertEqual(rrhh_novedades._rrhh_oracle_last_imported_date_sync(), "2026-10-06")

    def test_falls_back_to_legacy_oracle_rows_without_checkpoint_batches(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn:
                conn.execute("INSERT INTO rrhh_actividad_diaria VALUES (1, '2026-10-05', 'oracle_auto')")

        self.assertEqual(rrhh_novedades._rrhh_oracle_last_imported_date_sync(), "2026-10-05")

    def test_oracle_failure_keeps_existing_batch_untouched(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO rrhh_import_batches VALUES (7, 'oracle_actividad_20261013', 'old', 'rrhh', 'complete', '{}')"
                )

        with (
            patch.object(rrhh_novedades, "_latest_legajero_rows_for_oracle", return_value=[{"legajo": "1"}]),
            patch.object(rrhh_novedades, "_query_rrhh_presencias_jdbc", side_effect=RuntimeError("Oracle timeout")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Oracle timeout"):
                rrhh_novedades._import_oracle_activity_sync("2026-10-13", force=True)

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT batch_id, status FROM rrhh_import_batches WHERE batch_key = 'oracle_actividad_20261013'"
            ).fetchone()
        self.assertEqual(row, (7, "complete"))

    def test_oracle_activity_replacement_is_batched_and_normalizes_legajo(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE rrhh_actividad_diaria ("
            + ", ".join(f"{column} TEXT" for column in rrhh_novedades.ACTIVIDAD_INSERT_COLUMNS)
            + ")"
        )
        existing = {column: "" for column in rrhh_novedades.ACTIVIDAD_INSERT_COLUMNS}
        existing.update({"batch_id": "1", "legajo": "0001", "fecha": "2026-10-06"})
        conn.execute(
            f"INSERT INTO rrhh_actividad_diaria ({', '.join(existing)}) VALUES ({', '.join('?' for _ in existing)})",
            tuple(existing.values()),
        )
        replacement = dict(existing)
        replacement.update({"batch_id": "2", "legajo": "1", "origen_dato": "oracle_auto"})

        stats = rrhh_novedades._insert_actividad_payload(
            conn.cursor(),
            [tuple(replacement[column] for column in rrhh_novedades.ACTIVIDAD_INSERT_COLUMNS)],
            source="oracle_auto",
        )

        self.assertEqual(stats, {"inserted": 1, "updated": 1, "skipped_existing_oracle": 0})
        rows = conn.execute("SELECT batch_id, legajo FROM rrhh_actividad_diaria").fetchall()
        self.assertEqual([tuple(row) for row in rows], [("2", "1")])
        conn.close()


if __name__ == "__main__":
    unittest.main()
