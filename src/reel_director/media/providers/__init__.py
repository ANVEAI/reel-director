"""Provider registry: build every source from settings, report which are live, default search orders.

Each module exposes `provider(settings=None, **kw)`. A module another team has not landed yet (or one that fails
to import) is reported in status() as missing instead of breaking the free sources. Keyed sources (Pixabay,
Unsplash, Coverr) are built without a key but stay `available=False` and return nothing until a key is set:
  PIXABAY_API_KEY / settings media.pixabay_key        https://pixabay.com/api/docs/
  UNSPLASH_ACCESS_KEY / settings media.unsplash_key   https://unsplash.com/oauth/applications
  COVERR_API_KEY / settings media.coverr_key          https://api.coverr.co/docs/
"""
from __future__ import annotations

import importlib
import logging
from typing import Mapping

log = logging.getLogger(__name__)

FREE = ("library", "openverse", "wikimedia", "nasa", "archive", "webcapture")      # no key, no cost
KEYED = ("pixabay", "unsplash", "coverr")                                           # free, need a key
OTHER = ("youtube_cc", "claude_clip", "veo", "higgsfield")                          # other teams' sources
ALL = FREE + KEYED + OTHER
PAID = ("veo", "higgsfield")
# Default order per kind: own media first, then the stock sites with the best hit rate for modern B-roll, then
# the archives. webcapture only answers URL queries; paid generators are never in a default order.
DEFAULT_ORDER = {
    "image": ("library", "unsplash", "pixabay", "openverse", "wikimedia", "nasa", "webcapture"),
    "video": ("library", "coverr", "pixabay", "wikimedia", "nasa", "archive", "youtube_cc", "claude_clip"),
}


def load(name: str):
    """The provider module, or None if it is missing / broken (logged)."""
    if name not in ALL:
        raise KeyError(f"unknown media provider {name!r} (have: {', '.join(ALL)})")
    try:
        return importlib.import_module(f"{__name__}.{name}")
    except Exception as e:          # noqa: BLE001 - another team's module must not break the free sources
        log.warning("media provider %s unavailable: %s", name, e)
        return None


def make(name: str, settings: Mapping | None = None, **kw):
    """Module factory `provider(settings)`; else the module's provider class (name == module name, has search)."""
    mod = load(name)
    if mod is None:
        return None
    if callable(getattr(mod, "provider", None)):
        return mod.provider(settings, **kw)
    cls = next((v for v in vars(mod).values() if isinstance(v, type) and getattr(v, "name", None) == name
                and hasattr(v, "search") and v.__module__ == mod.__name__), None)
    if cls is None:
        return None
    return cls.from_settings(settings, **kw) if hasattr(cls, "from_settings") else cls(**kw)


def build(names=None, settings: Mapping | None = None, **kw) -> dict:
    """{name: provider} for `names` (default: the free + keyed sources), skipping missing modules.
    kw (http=, cache=) is passed to our own providers only; other teams' factories get settings alone."""
    out = {}
    for n in names or FREE + KEYED:
        p = make(n, settings, **(kw if n in FREE + KEYED else {}))
        if p is not None:
            out[n] = p
    return out


def available(providers: Mapping) -> dict:
    return {n: p for n, p in providers.items() if getattr(p, "available", True)}


def status(settings: Mapping | None = None, names=ALL) -> list[dict]:
    """One row per source for Studio/CLI: available, kinds, paid, what to set up."""
    rows = []
    for n in names:
        try:
            p = make(n, settings)
            if p is None:
                rows.append({"provider": n, "available": False, "setup": "not installed"})
            elif hasattr(p, "status"):
                rows.append({"provider": n, **p.status()})
            else:
                rows.append({"provider": n, "available": bool(getattr(p, "available", True))})
        except Exception as e:      # noqa: BLE001
            rows.append({"provider": n, "available": False, "setup": f"failed to start: {e}"})
    return rows


def order(kind: str, providers: Mapping, prefer=None) -> list[str]:
    """Search order: the cue's preferred list first (as given), then the default order, available ones only (plus
    sources that serve their cache while unavailable: claude_clip's accepted clips when the CLI is logged out)."""
    seq = list(prefer or ()) + [n for n in DEFAULT_ORDER.get(kind, ()) if n not in (prefer or ())]
    return [n for n in seq if n in providers and (getattr(providers[n], "available", True)
                                                  or getattr(providers[n], "serves_cache", False))]
