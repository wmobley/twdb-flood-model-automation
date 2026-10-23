"""Small, validated configuration boundary for future model-run coordination."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True)
class RunConfig:
    """Configuration needed to identify an initial model run."""

    name: str
    model_family: str
    model_path: str
    output_path: str
    plan: str
    concurrency: int = 1

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "RunConfig":
        required = ("name", "model_family", "model_path", "output_path", "plan")
        missing = [key for key in required if not values.get(key)]
        if missing:
            raise ValueError(f"Missing required run configuration fields: {', '.join(missing)}")

        concurrency = int(values.get("concurrency", 1))
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")

        return cls(
            name=str(values["name"]),
            model_family=str(values["model_family"]),
            model_path=str(values["model_path"]),
            output_path=str(values["output_path"]),
            plan=str(values["plan"]),
            concurrency=concurrency,
        )


def load_run_config(path: str | Path) -> RunConfig:
    """Load and validate a YAML run configuration."""

    config_path = Path(path)
    with config_path.open(encoding="utf-8") as stream:
        values = yaml.safe_load(stream) or {}
    if not isinstance(values, Mapping):
        raise ValueError("Run configuration must contain a YAML mapping")
    return RunConfig.from_mapping(values)
