from __future__ import annotations

from uuid import uuid4

import pytest

from rag_eval_api.services.experiment_snapshots import ExperimentSnapshotInput, create_snapshot


def test_experiment_snapshot_contains_versioned_inputs_and_environment_hash() -> None:
    snapshot = create_snapshot(
        ExperimentSnapshotInput(
            dataset_version_id=uuid4(),
            adapter_config_id=uuid4(),
            adapter_version="adapter-v1",
            model_provider_id=uuid4(),
            model_name="model-a",
            metric_versions={"recall": "retrieval-v1"},
            parameters={"top_k": 5},
            random_seed=17,
            environment={"python": "3.12", "platform": "test"},
        )
    )

    assert snapshot.dataset_version_id
    assert snapshot.adapter_version == "adapter-v1"
    assert snapshot.random_seed == 17
    assert len(snapshot.environment_hash) == 64
    assert snapshot.parameters == {"top_k": 5}


def test_experiment_snapshot_rejects_unbounded_parameter_payload() -> None:
    with pytest.raises(ValueError, match="parameters"):
        create_snapshot(
            ExperimentSnapshotInput(
                dataset_version_id=uuid4(),
                adapter_config_id=uuid4(),
                adapter_version="adapter-v1",
                model_provider_id=uuid4(),
                model_name="model-a",
                metric_versions={},
                parameters={"prompt": "x" * 70_001},
                random_seed=1,
                environment={},
            )
        )
