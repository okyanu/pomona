from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.config import settings


def discover_models(models_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    root = models_dir or settings.models_dir
    models: List[Dict[str, Any]] = []

    if not root.exists():
        return models

    patterns = [root.glob("*.yaml"), root.rglob("pomona-model.yaml")]
    seen: set[str] = set()
    for pattern in patterns:
        for path in sorted(pattern):
            if path.name.startswith(".") or str(path) in seen:
                continue
            seen.add(str(path))
            with path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            data["_path"] = str(path.relative_to(root))
            models.append(data)

    return models


def get_model(model_id: str, models_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    for model in discover_models(models_dir):
        if model.get("id") == model_id:
            return model
    return None
