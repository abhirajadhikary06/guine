from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import os
import tempfile

# Prevent local .env loading so tests always use isolated SQLite.
os.environ["GUINE_DISABLE_DOTENV"] = "1"
# Force local SQLite for tests, not D1
os.environ.pop("CLOUDFLARE_D1_DATABASE_ID", None)
os.environ.pop("CLOUDFLARE_ACCOUNT_ID", None)
os.environ.pop("CLOUDFLARE_API_TOKEN", None)
TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="guine-tests-"))
os.environ["GUINE_DB_PATH"] = str(TEST_DB_DIR / "guine.sqlite3")
os.environ.setdefault("GUINE_SESSION_SECRET", "test-secret")
os.environ.setdefault("GUINE_SESSION_SAME_SITE", "lax")
os.environ.setdefault("GUINE_SESSION_HTTPS_ONLY", "false")
