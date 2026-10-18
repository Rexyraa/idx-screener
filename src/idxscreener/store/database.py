from __future__ import annotations

import sqlite3
from pathlib import Path

from .migrations import MigrationManager


class StockDatabase:
    def __init__(self, database_url: str = "sqlite:///idxscreener.db"):
        self.database_url = database_url
        self.database_path = self._resolve_database_path(database_url)
        self.migration_manager = MigrationManager(self.database_path)

    @staticmethod
    def _resolve_database_path(database_url: str) -> Path:
        if not database_url.startswith("sqlite://"):
            raise ValueError("Only sqlite database URLs are supported in this phase")
        cleaned = database_url.replace("sqlite:///", "", 1)
        if cleaned.startswith("/") and len(cleaned) > 2 and cleaned[2] == ":":
            return Path(cleaned)
        return Path(cleaned)

    def initialize(self) -> "StockDatabase":
        self.migration_manager.apply_all()
        return self

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @property
    def engine(self):
        return self.database_path
