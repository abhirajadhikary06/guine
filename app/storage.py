from __future__ import annotations

import hashlib
import hmac
import os
import random
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


AVATAR_FILENAMES = [
    "image.png",
    "image1.png",
    "image2.png",
    "image3.png",
    "image4.png",
]


@dataclass(slots=True)
class UserRecord:
    id: int
    name: str
    email: str
    password_hash: str
    avatar_file: str
    created_at: str

    @property
    def avatar_url(self) -> str:
        base_url = os.environ.get("GUINE_AVATAR_BASE_URL", "/static").rstrip("/")
        return f"{base_url}/{self.avatar_file}"

    def to_public_dict(self) -> dict[str, str | int]:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "avatar": self.avatar_url,
            "avatar_file": self.avatar_file,
            "created_at": self.created_at,
        }


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = stored_hash.split("$")
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return hmac.compare_digest(candidate, expected)


class UserStore:
    def __init__(self, db_path: str | Path | None = None):
        default_path = Path(os.environ.get("GUINE_DB_PATH", "/tmp/guine.sqlite3"))
        self.db_path = Path(db_path) if db_path is not None else default_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_schema(self) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        email TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        avatar_file TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                connection.commit()

    def _row_to_user(self, row: sqlite3.Row | None) -> UserRecord | None:
        if row is None:
            return None
        return UserRecord(
            id=row["id"],
            name=row["name"],
            email=row["email"],
            password_hash=row["password_hash"],
            avatar_file=row["avatar_file"],
            created_at=row["created_at"],
        )

    def get_user_by_id(self, user_id: int) -> UserRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return self._row_to_user(row)

    def get_user_by_email(self, email: str) -> UserRecord | None:
        normalized = email.strip().lower()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE email = ?",
                (normalized,),
            ).fetchone()
        return self._row_to_user(row)

    def create_user(self, name: str, email: str, password: str) -> UserRecord:
        normalized_email = email.strip().lower()
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Name is required.")
        if not normalized_email:
            raise ValueError("Email is required.")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long.")

        avatar_file = random.choice(AVATAR_FILENAMES)
        password_hash = _hash_password(password)
        created_at = datetime.now(timezone.utc).isoformat()

        with self._lock:
            with self._connect() as connection:
                try:
                    cursor = connection.execute(
                        """
                        INSERT INTO users (name, email, password_hash, avatar_file, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (clean_name, normalized_email, password_hash, avatar_file, created_at),
                    )
                    connection.commit()
                except sqlite3.IntegrityError as exc:
                    raise ValueError("An account with that email already exists.") from exc

                row = connection.execute(
                    "SELECT * FROM users WHERE id = ?",
                    (cursor.lastrowid,),
                ).fetchone()

        user = self._row_to_user(row)
        if user is None:
            raise RuntimeError("Failed to create user.")
        return user

    def authenticate(self, email: str, password: str) -> UserRecord | None:
        user = self.get_user_by_email(email)
        if user is None:
            return None
        return user if _verify_password(password, user.password_hash) else None
