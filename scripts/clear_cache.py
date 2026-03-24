#!/usr/bin/env python3
"""Clear all caches (in-memory, SQLite, vector DB).

This script helps debug caching issues by clearing all cached data.
"""

import shutil
from pathlib import Path


def clear_caches():
    """Clear all cache files."""
    project_root = Path(__file__).parent.parent

    cache_locations = [
        project_root / "dev_data" / "starboard_vector.db",
        project_root / "dev_data" / "cache.db",
        project_root / ".cache",
        project_root / "__pycache__",
    ]

    print("🧹 Clearing Caches\n")

    for cache_path in cache_locations:
        if cache_path.exists():
            if cache_path.is_file():
                cache_path.unlink()
                print(f"✅ Deleted: {cache_path}")
            elif cache_path.is_dir():
                shutil.rmtree(cache_path)
                print(f"✅ Deleted directory: {cache_path}")
        else:
            print(f"⏭️  Not found: {cache_path}")

    # Clear Python cache recursively
    for pycache in project_root.rglob("__pycache__"):
        shutil.rmtree(pycache)
        print(f"✅ Deleted: {pycache}")

    print("\n✅ All caches cleared!")
    print("\n⚠️  Next steps:")
    print("   1. Restart the server: make dev-server")
    print("   2. Clear browser cache/cookies")
    print("   3. Try your query again")


if __name__ == "__main__":
    clear_caches()
