#!/usr/bin/env python3
"""Test D1 integration by attempting a real query."""
import os
import sys

# Set D1 env vars
os.environ["CLOUDFLARE_D1_DATABASE_ID"] = "e0eae61b-ab99-4818-a1bc-6d98b64ead17"
os.environ["CLOUDFLARE_API_TOKEN"] = "cfut_9EbOq47rg0f8wzLrXUjTmdFRAIWRap8vDFBEBkzhc670718f"
os.environ["CLOUDFLARE_ACCOUNT_ID"] = "4e6032576be9e2177a1b987410d90ce1"

sys.path.insert(0, "/workspaces/guine")

from app.storage import UserStore

def test_d1_connection():
    """Try to create a UserStore with D1."""
    print("Creating UserStore with D1...")
    try:
        store = UserStore(use_d1=True)
        print(f"✓ UserStore created, using D1: {store._use_d1}")
        print(f"  Account ID: {store.account_id}")
        print(f"  Database ID: {store.database_id}")
        
        # Try a simple query
        print("\nTesting D1 query...")
        try:
            result = store._d1_query("SELECT name FROM sqlite_master LIMIT 1")
            print(f"✓ D1 query successful: {result}")
        except Exception as e:
            print(f"✗ D1 query failed: {e}")
            return False
        
        return True
    except Exception as e:
        print(f"✗ Failed to create UserStore: {e}")
        return False

def test_local_fallback():
    """Test that local SQLite still works."""
    print("\n\nCreating UserStore with local SQLite fallback...")
    os.environ.pop("CLOUDFLARE_D1_DATABASE_ID", None)
    os.environ.pop("CLOUDFLARE_ACCOUNT_ID", None)
    os.environ.pop("CLOUDFLARE_API_TOKEN", None)
    
    try:
        store = UserStore()
        print(f"✓ UserStore created, using D1: {store._use_d1}")
        
        # Try signup
        print("\nTesting local signup...")
        user = store.create_user("Test User", "test@local.dev", "password123")
        print(f"✓ User created: {user.name} ({user.email})")
        
        # Try login
        print("\nTesting local login...")
        authenticated = store.authenticate("test@local.dev", "password123")
        if authenticated:
            print(f"✓ Auth successful for {authenticated.email}")
        else:
            print("✗ Auth failed")
            return False
        
        return True
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success_d1 = test_d1_connection()
    success_local = test_local_fallback()
    
    print("\n" + "="*60)
    if success_d1:
        print("✓ D1 integration ready!")
    else:
        print("⚠ D1 not accessible (may need to verify API token)")
    
    if success_local:
        print("✓ Local SQLite fallback working!")
    else:
        print("✗ Local SQLite failed")
    
    sys.exit(0 if success_local else 1)
