from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from rag_eval_api.worker import ReadinessFile, WorkerRuntime


def test_readiness_file_is_atomic_and_only_owner_can_remove(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "worker.ready"
    readiness = ReadinessFile(path)

    owner_token = readiness.write()

    assert path.is_file()
    assert path.read_text(encoding="utf-8") == owner_token
    readiness.remove(owner_token + "-other-process")
    assert path.is_file()
    readiness.remove(owner_token)
    assert not path.exists()


def test_worker_runtime_rejects_non_positive_poll_interval() -> None:
    with pytest.raises(ValueError, match="poll_interval"):
        WorkerRuntime(
            worker=object(),  # type: ignore[arg-type]
            redis=object(),  # type: ignore[arg-type]
            readiness_file=ReadinessFile("/tmp/worker-ready"),
            poll_interval=timedelta(seconds=0),
        )
