"""Project-scoped validation for experiment drafts before persistence."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.auth.rbac import ProjectAccess
from rag_eval_api.models import (
    AdapterConfig,
    AdapterTestStatus,
    CandidateDatasetStatus,
    CandidateDatasetVersion,
    ModelProviderConfig,
)
from rag_eval_api.schemas.experiments import ExperimentDraftRequest, ValidatedExperimentDraft


class ExperimentDraftValidationError(ValueError):
    """Stable validation failure safe to map at an API boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def validate_experiment_draft(
    db_session: AsyncSession,
    access: ProjectAccess,
    payload: ExperimentDraftRequest,
) -> ValidatedExperimentDraft:
    """Validate all mutable references while retaining the tenant boundary."""

    if payload.random_seed is None:
        raise ExperimentDraftValidationError("random_seed_required", "An explicit random seed is required.")
    parameter_bytes = json.dumps(
        payload.parameters, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    if len(parameter_bytes) > 64 * 1024:
        raise ExperimentDraftValidationError("parameters_too_large", "Experiment parameters exceed 64 KiB.")

    dataset_version = await db_session.scalar(
        select(CandidateDatasetVersion).where(
            CandidateDatasetVersion.id == payload.dataset_version_id,
            CandidateDatasetVersion.organization_id == access.actor.organization_id,
            CandidateDatasetVersion.project_id == access.project.id,
        )
    )
    if dataset_version is None:
        raise ExperimentDraftValidationError("not_found", "Dataset version was not found.")
    if dataset_version.status is not CandidateDatasetStatus.published:
        raise ExperimentDraftValidationError(
            "dataset_version_unpublished", "Only a published dataset version can start an experiment."
        )

    adapter = await db_session.scalar(
        select(AdapterConfig).where(
            AdapterConfig.id == payload.adapter_config_id,
            AdapterConfig.organization_id == access.actor.organization_id,
            AdapterConfig.project_id == access.project.id,
        )
    )
    if adapter is None or not adapter.enabled or adapter.last_test_status is not AdapterTestStatus.succeeded:
        raise ExperimentDraftValidationError(
            "adapter_unavailable", "Adapter must be enabled and pass a connection test before starting."
        )

    provider = await db_session.scalar(
        select(ModelProviderConfig).where(
            ModelProviderConfig.id == payload.model_provider_id,
            ModelProviderConfig.organization_id == access.actor.organization_id,
            ModelProviderConfig.project_id == access.project.id,
        )
    )
    if provider is None or not provider.enabled:
        raise ExperimentDraftValidationError(
            "provider_unavailable", "Model provider must be enabled before starting."
        )

    return ValidatedExperimentDraft(
        name=payload.name,
        dataset_version_id=dataset_version.id,
        dataset_item_count=dataset_version.item_count,
        adapter_config_id=adapter.id,
        adapter_version=adapter.adapter_version,
        model_provider_id=provider.id,
        model_name=provider.model_name,
        metric_versions=dict(payload.metric_versions),
        parameters=dict(payload.parameters),
        random_seed=payload.random_seed,
    )
