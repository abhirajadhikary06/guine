from __future__ import annotations

import hashlib
import hmac
import os
import random
import json
import urllib.request
import urllib.error
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

if os.environ.get("GUINE_DISABLE_DOTENV", "").lower() not in {"1", "true", "yes"}:
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except Exception:
        pass


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
    def __init__(self, use_d1: bool | None = None):
        self._use_d1 = use_d1 if use_d1 is not None else bool(os.environ.get("CLOUDFLARE_D1_DATABASE_ID"))
        if self._use_d1:
            self.account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
            self.database_id = os.environ.get("CLOUDFLARE_D1_DATABASE_ID", "")
            self.api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
            if not all([self.account_id, self.database_id, self.api_token]):
                raise ValueError("D1 credentials missing: CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_D1_DATABASE_ID, CLOUDFLARE_API_TOKEN")
            self._lock = threading.Lock()
            self._initialize_schema()
        else:
            # Fallback to local SQLite
            default_path = Path(os.environ.get("GUINE_DB_PATH", "/tmp/guine.sqlite3"))
            self.db_path = Path(default_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._lock = threading.Lock()
            self._initialize_schema_local()

    def _d1_query(self, sql: str, params: list | None = None) -> list[dict] | None:
        """Execute a D1 query via REST API. Returns list of rows or None."""
        url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/d1/database/{self.database_id}/query"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
        body = json.dumps({"sql": sql, "params": params or []}).encode("utf-8")
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                if data.get("success"):
                    result = data.get("result", [])
                    if result and isinstance(result, list):
                        first = result[0]
                        if isinstance(first, dict) and "results" in first:
                            return first.get("results", [])
                    return result
                else:
                    raise ValueError(f"D1 error: {data.get('errors', 'Unknown error')}")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise ValueError(f"D1 API error ({e.code}): {error_body}")
        except Exception as e:
            raise ValueError(f"D1 query failed: {str(e)}")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_schema_local(self) -> None:
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

    def _initialize_schema(self) -> None:
        if self._use_d1:
            # D1 schema is already initialized on Cloudflare; just verify it exists
            try:
                self._d1_query("SELECT 1 FROM users LIMIT 1")
            except ValueError:
                # Table doesn't exist yet; this is expected if schema.sql wasn't run
                pass
        else:
            self._initialize_schema_local()

    def _row_to_user(self, row: sqlite3.Row | None) -> UserRecord | None:
        if row is None:
            return None
        # Handle both sqlite3.Row and dict (from D1 API)
        if isinstance(row, dict):
            return UserRecord(
                id=int(row.get("id", 0)),
                name=str(row.get("name", "")),
                email=str(row.get("email", "")),
                password_hash=str(row.get("password_hash", "")),
                avatar_file=str(row.get("avatar_file", "")),
                created_at=str(row.get("created_at", "")),
            )
        return UserRecord(
            id=row["id"],
            name=row["name"],
            email=row["email"],
            password_hash=row["password_hash"],
            avatar_file=row["avatar_file"],
            created_at=row["created_at"],
        )

    def get_user_by_id(self, user_id: int) -> UserRecord | None:
        if self._use_d1:
            with self._lock:
                try:
                    results = self._d1_query("SELECT * FROM users WHERE id = ?", [user_id])
                    row = results[0] if results else None
                except Exception:
                    return None
            return self._row_to_user(row)
        else:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM users WHERE id = ?",
                    (user_id,),
                ).fetchone()
            return self._row_to_user(row)

    def get_user_by_email(self, email: str) -> UserRecord | None:
        normalized = email.strip().lower()
        if self._use_d1:
            with self._lock:
                try:
                    results = self._d1_query("SELECT * FROM users WHERE email = ?", [normalized])
                    row = results[0] if results else None
                except Exception:
                    return None
            return self._row_to_user(row)
        else:
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

        if self._use_d1:
            with self._lock:
                try:
                    self._d1_query(
                        """
                        INSERT INTO users (name, email, password_hash, avatar_file, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        [clean_name, normalized_email, password_hash, avatar_file, created_at],
                    )
                except ValueError as exc:
                    if "UNIQUE constraint failed" in str(exc) or "already exists" in str(exc):
                        raise ValueError("An account with that email already exists.") from exc
                    raise

                # Fetch the newly created user by email
                results = self._d1_query("SELECT * FROM users WHERE email = ?", [normalized_email])
                row = results[0] if results else None
        else:
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
