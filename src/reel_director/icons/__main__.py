from . import sync, ids

print("reel.css icons", "updated" if sync() else "already in sync", f"({len(ids())} glyphs)")
