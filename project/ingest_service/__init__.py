from __future__ import annotations

import importlib
import sys

_knowledge = importlib.import_module("services.ingest_service.knowledge")
sys.modules[__name__ + ".knowledge"] = _knowledge

__all__ = ["knowledge"]
