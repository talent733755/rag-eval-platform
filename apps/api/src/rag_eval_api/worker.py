"""Standalone durable worker process for document ingestion."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import tempfile
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from rag_eval_api.adapters import Adapter, HttpAdapter, load_python_adapter
from rag_eval_api.adapters.errors import AdapterError
from rag_eval_api.candidates.provider import OpenAICompatibleCandidateGenerator
from rag_eval_api.config import Settings, get_settings
from rag_eval_api.db import create_engine
from rag_eval_api.models import AdapterConfig, AdapterKind
from rag_eval_api.parsers.registry import ParserRegistry
from rag_eval_api.services.candidate_worker import CandidateWorker
from rag_eval_api.services.experiment_worker import ExperimentWorker
from rag_eval_api.services.worker import IngestionWorker, WorkerBatchResult
from rag_eval_api.storage.local import LocalBlobStore
from rag_eval_api.storage.protocol import BlobStore

LOGGER = logging.getLogger("rag_eval_api.worker")


class CombinedWorker:
    """Run parse and candidate jobs behind one runtime polling loop."""

    def __init__(
        self,
        ingestion: IngestionWorker,
        candidates: CandidateWorker | None,
        experiments: ExperimentWorker | None = None,
    ) -> None:
        self.ingestion = ingestion
        self.candidates = candidates
        self.experiments = experiments
        self.batch_size = ingestion.batch_size
        self.session_factory = ingestion.session_factory

    def request_shutdown(self) -> None:
        self.ingestion.request_shutdown()
        if self.candidates is not None:
            self.candidates.request_shutdown()

    async def process_batch(self, limit: int) -> WorkerBatchResult:
        parse_result = await self.ingestion.process_batch(limit)
        if parse_result.processed:
            return parse_result
        if self.candidates is None:
            candidate_result = None
        else:
            candidate_result = await self.candidates.process_batch(limit)
        if candidate_result is not None and candidate_result.processed:
            return WorkerBatchResult(
                processed=candidate_result.processed,
                succeeded=candidate_result.succeeded,
                failed=candidate_result.failed,
                cancelled=candidate_result.cancelled,
                lease_lost=candidate_result.lease_lost,
            )
        if self.experiments is None:
            return parse_result
        experiment_result = await self.experiments.process_batch(limit)
        return WorkerBatchResult(
            processed=experiment_result.processed,
            succeeded=experiment_result.succeeded,
            failed=experiment_result.failed,
            cancelled=experiment_result.cancelled,
            lease_lost=experiment_result.lease_lost,
        )

    async def run_maintenance(self) -> None:
        await self.ingestion.run_maintenance()
        if self.candidates is not None:
            await self.candidates.run_maintenance()
        if self.experiments is not None:
            await self.experiments.run_maintenance()


class ReadinessFile:
    """An atomically written readiness marker owned by one worker process."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("readiness file path must be absolute")

    def write(self) -> str:
        """Write a process token atomically and return it to the owner."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = f"{os.getpid()}:{os.urandom(16).hex()}"
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            dir=self.path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(token)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, self.path)
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name)
            raise
        return token

    def remove(self, owner_token: str) -> bool:
        """Remove the marker only if it still contains this process token."""

        try:
            current_token = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False
        if current_token != owner_token:
            return False
        try:
            self.path.unlink()
        except FileNotFoundError:
            return False
        return True


class WorkerRuntime:
    """Poll PostgreSQL-backed work and use Redis only as an optional wakeup hint."""

    def __init__(
        self,
        *,
        worker: CombinedWorker,
        redis: Redis | Any,
        readiness_file: ReadinessFile,
        poll_interval: timedelta,
        maintenance_interval: timedelta = timedelta(minutes=5),
        hint_channel: str = "rag-eval:worker:hints",
        database_probe: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if poll_interval <= timedelta(0):
            raise ValueError("poll_interval must be positive")
        if maintenance_interval <= timedelta(0):
            raise ValueError("maintenance_interval must be positive")
        if not hint_channel.strip():
            raise ValueError("hint_channel must not be empty")
        self.worker = worker
        self.redis = redis
        self.readiness_file = readiness_file
        self.poll_interval = poll_interval
        self.maintenance_interval = maintenance_interval
        self.hint_channel = hint_channel
        self.database_probe = database_probe
        self._shutdown = asyncio.Event()
        self._readiness_token: str | None = None

    def request_shutdown(self) -> None:
        """Stop polling and ask the worker to cancel the active operation."""

        self._shutdown.set()
        self.worker.request_shutdown()

    async def run_once(self) -> bool:
        """Probe dependencies, publish readiness, and process one bounded batch."""

        await self._probe_database()
        self._ensure_ready()
        result = await self.worker.process_batch(self.worker.batch_size)
        return result.processed > 0

    async def run(self) -> None:
        """Run until a signal requests graceful shutdown."""

        await self._probe_database()
        self._ensure_ready()
        next_maintenance = asyncio.get_running_loop().time()
        try:
            while not self._shutdown.is_set():
                now = asyncio.get_running_loop().time()
                if now >= next_maintenance:
                    await self.worker.run_maintenance()
                    next_maintenance = now + self.maintenance_interval.total_seconds()
                result = await self.worker.process_batch(self.worker.batch_size)
                if result.processed:
                    continue
                await self._wait_for_hint_or_timeout()
        finally:
            self.request_shutdown()
            if self._readiness_token is not None:
                self.readiness_file.remove(self._readiness_token)
                self._readiness_token = None

    async def close(self) -> None:
        """Release the Redis client after the runtime loop has stopped."""

        close = getattr(self.redis, "aclose", None)
        if close is not None:
            await close()

    async def _probe_database(self) -> None:
        if self.database_probe is not None:
            await self.database_probe()
            return
        session_factory = self.worker.session_factory
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))

    def _ensure_ready(self) -> None:
        if self._readiness_token is None:
            self._readiness_token = self.readiness_file.write()

    async def _wait_for_hint_or_timeout(self) -> None:
        """Use a Redis list hint when available, while always retaining DB polling."""

        timeout = self.poll_interval.total_seconds()
        blpop = getattr(self.redis, "blpop", None)
        if blpop is None:
            await self._wait_for_shutdown_or_timeout(timeout)
            return
        try:
            await asyncio.wait_for(blpop(self.hint_channel, timeout=max(1, int(timeout))), timeout)
        except TimeoutError:
            return
        except Exception:
            LOGGER.warning(
                "worker Redis hint unavailable; continuing database polling",
                extra={"event": "worker.redis_hint_unavailable"},
            )

    async def _wait_for_shutdown_or_timeout(self, seconds: float) -> None:
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._shutdown.wait(), timeout=seconds)


async def _build_runtime(settings: Settings) -> tuple[WorkerRuntime, AsyncEngine, LocalBlobStore]:
    engine = create_engine(settings)
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    blob_store = LocalBlobStore(settings.blob_root, max_bytes=settings.max_upload_bytes)
    parser_registry = ParserRegistry(runner=settings.parser_runner())
    worker = IngestionWorker(
        session_factory=session_factory,
        blob_store=cast(BlobStore, blob_store),
        parser_registry=parser_registry,
        parser_limits=settings.parser_limits(),
        worker_id=f"worker-{os.getpid()}",
        lease_ttl=timedelta(seconds=settings.worker_lease_ttl_seconds),
        batch_size=settings.worker_batch_size,
        heartbeat_interval=timedelta(seconds=settings.worker_heartbeat_interval_seconds),
        orphan_blob_grace_period=timedelta(seconds=settings.orphan_blob_grace_seconds),
    )
    candidate_worker = None
    if settings.provider_base_url is not None and settings.provider_api_key is not None:
        generator = OpenAICompatibleCandidateGenerator(
            settings.provider_base_url,
            api_key=settings.provider_api_key.get_secret_value(),
            model_name=settings.provider_model_name,
            app_env=settings.app_env,
            allowed_hosts=settings.provider_allowed_hosts,
            allowed_ports=settings.provider_allowed_ports,
            timeout_seconds=settings.provider_timeout_seconds,
        )
        candidate_worker = CandidateWorker(
            session_factory=session_factory,
            generator=generator,
            worker_id=f"candidate-worker-{os.getpid()}",
            lease_ttl=timedelta(seconds=settings.worker_lease_ttl_seconds),
            batch_size=settings.worker_batch_size,
            heartbeat_interval=timedelta(seconds=settings.worker_heartbeat_interval_seconds),
        )

    def build_adapter(config: AdapterConfig) -> Adapter:
        if config.kind is AdapterKind.python:
            return load_python_adapter(
                config.entrypoint_ref,
                adapter_version=config.adapter_version,
                trace_level=config.trace_level,
                timeout_seconds=config.timeout_seconds,
            )
        token = os.getenv(config.credential_ref) if config.credential_ref else None
        if config.credential_ref and token is None:
            raise AdapterError(
                "adapter_credentials_unavailable",
                "Adapter credential reference is not available.",
            )
        if not config.endpoint:
            raise AdapterError("adapter_unavailable", "Adapter endpoint is unavailable.")
        return HttpAdapter(
            config.endpoint,
            bearer_token=token,
            adapter_version=config.adapter_version,
            trace_level=config.trace_level,
            app_env=settings.app_env,
            allowed_hosts=settings.provider_allowed_hosts,
            allowed_ports=settings.provider_allowed_ports,
            timeout_seconds=config.timeout_seconds,
        )

    experiment_worker = ExperimentWorker(
        session_factory=session_factory,
        adapter_factory=build_adapter,
        worker_id=f"experiment-worker-{os.getpid()}",
        lease_ttl=timedelta(seconds=settings.worker_lease_ttl_seconds),
        blob_store=cast(BlobStore, blob_store),
    )
    combined_worker = CombinedWorker(worker, candidate_worker, experiment_worker)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    runtime = WorkerRuntime(
        worker=combined_worker,
        redis=redis,
        readiness_file=ReadinessFile(settings.worker_readiness_file),
        poll_interval=timedelta(seconds=settings.worker_poll_interval_seconds),
        hint_channel=settings.worker_redis_hint_channel,
    )
    return runtime, engine, blob_store


def _install_signal_handlers(runtime: WorkerRuntime) -> None:
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal_name, runtime.request_shutdown)


async def _async_main(settings: Settings, *, once: bool) -> int:
    if not settings.worker_enabled:
        LOGGER.info("worker disabled", extra={"event": "worker.disabled"})
        return 0
    runtime, engine, blob_store = await _build_runtime(settings)
    try:
        _install_signal_handlers(runtime)
        if once:
            await runtime.run_once()
        else:
            await runtime.run()
    finally:
        await runtime.close()
        await engine.dispose()
        blob_store.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the RAG Eval Platform durable worker")
    parser.add_argument("--once", action="store_true", help="process one bounded batch and exit")
    parser.add_argument("--poll-interval", type=float, help="override poll interval in seconds")
    parser.add_argument("--readiness-file", type=Path, help="override readiness marker path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    if args.poll_interval is not None:
        if not 0.1 <= args.poll_interval <= 60:
            raise SystemExit("--poll-interval must be between 0.1 and 60 seconds")
        settings.worker_poll_interval_seconds = args.poll_interval
    if args.readiness_file is not None:
        if not args.readiness_file.is_absolute():
            raise SystemExit("--readiness-file must be an absolute path")
        settings.worker_readiness_file = str(args.readiness_file)
    return asyncio.run(_async_main(settings, once=args.once))


if __name__ == "__main__":
    raise SystemExit(main())
