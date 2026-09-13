"""Application models imported here so metadata and migrations see every table."""

from rag_eval_api.models.adapters import AdapterConfig, AdapterKind, AdapterTestStatus
from rag_eval_api.models.audit_event import AuditEvent
from rag_eval_api.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, utc_now
from rag_eval_api.models.candidates import (
    CandidateDataset,
    CandidateDatasetItem,
    CandidateDatasetStatus,
    CandidateDatasetVersion,
    CandidateGenerationConfig,
    CandidateItemEvidence,
    CandidateReviewStatus,
)
from rag_eval_api.models.documents import (
    Document,
    DocumentChunk,
    DocumentParseStatus,
    DocumentSourceType,
    DocumentVersion,
)
from rag_eval_api.models.ingestion import (
    IngestionAttemptFinalStatus,
    IngestionJob,
    IngestionJobAttempt,
    IngestionJobKind,
    IngestionJobLease,
    IngestionJobStatus,
)
from rag_eval_api.models.membership import Membership, MembershipRole
from rag_eval_api.models.model_providers import ModelProviderConfig, ModelProviderTestStatus
from rag_eval_api.models.organization import Organization
from rag_eval_api.models.project import Project

__all__ = [
    "AuditEvent",
    "AdapterConfig",
    "AdapterKind",
    "AdapterTestStatus",
    "Base",
    "CandidateDataset",
    "CandidateDatasetItem",
    "CandidateDatasetVersion",
    "CandidateDatasetStatus",
    "CandidateGenerationConfig",
    "CandidateItemEvidence",
    "CandidateReviewStatus",
    "Document",
    "DocumentChunk",
    "DocumentParseStatus",
    "DocumentSourceType",
    "DocumentVersion",
    "IngestionJob",
    "IngestionJobAttempt",
    "IngestionAttemptFinalStatus",
    "IngestionJobKind",
    "IngestionJobLease",
    "IngestionJobStatus",
    "Membership",
    "MembershipRole",
    "ModelProviderConfig",
    "ModelProviderTestStatus",
    "Organization",
    "Project",
    "TimestampMixin",
    "UTCDateTime",
    "UUIDPrimaryKeyMixin",
    "utc_now",
]
