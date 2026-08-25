"""Core reconnaissance engine primitives.

The package deliberately has no dependency on FastAPI or the web UI.  API, CLI,
and workers are adapters around these services.
"""

from app.recon.normalization import NormalizedAsset, normalize_asset

__all__ = ["NormalizedAsset", "normalize_asset"]
