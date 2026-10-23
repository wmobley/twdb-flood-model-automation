from pathlib import Path

import pytest

from load_balancer import RunConfig, load_run_config


ROOT = Path(__file__).parents[1]


def test_example_run_config_loads() -> None:
    config = load_run_config(ROOT / "configs" / "example-run.yaml")

    assert isinstance(config, RunConfig)
    assert config.model_family == "hec-ras"
    assert config.concurrency == 1


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValueError, match="model_path"):
        RunConfig.from_mapping(
            {
                "name": "missing-model",
                "model_family": "hec-ras",
                "output_path": "run-outputs/missing-model",
                "plan": "plans/example-plan",
            }
        )


def test_non_positive_concurrency_is_rejected() -> None:
    with pytest.raises(ValueError, match="concurrency"):
        RunConfig.from_mapping(
            {
                "name": "bad-concurrency",
                "model_family": "hec-ras",
                "model_path": "models/example-model",
                "output_path": "run-outputs/bad-concurrency",
                "plan": "plans/example-plan",
                "concurrency": 0,
            }
        )
