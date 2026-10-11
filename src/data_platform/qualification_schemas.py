"""Immutable protocol schemas defined by RFC-006 qualification contracts."""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
import re
import unicodedata

from .qualification_serialization import (
    canonical_fingerprint,
    canonical_identity,
    canonical_json_bytes,
    parse_json_payload,
)


EVIDENCE_SCHEMA_VERSION = "provider-capability-evidence-v1"
CATALOGUE_SCHEMA_VERSION = "provider-capability-catalogue-v1"
PROFILE_SCHEMA_VERSION = "operation-qualification-profile-v1"
DECISION_SCHEMA_VERSION = "provider-qualification-decision-v1"
STRICT_SCOPE_QUALIFIED_V1 = "STRICT_SCOPE_QUALIFIED_V1"

STABLE_CAPABILITY_IDS = (
    "CANONICAL_OHLCV_COMPLETENESS",
    "CASH_DIVIDEND_EVIDENCE",
    "DATE_RANGE_MINIMUM_HISTORY",
    "DELISTING_HANDLING",
    "DIVIDEND_ENTITLEMENT_PAYMENT_EVIDENCE",
    "FAILURE_BEHAVIOR",
    "INCREMENTAL_ACQUISITION_OVERLAP",
    "MERGER_ECONOMIC_TERMS_EVIDENCE",
    "OPERATIONAL_AVAILABILITY_PUBLICATION_LAG",
    "PAGINATION_RATE_LIMIT_COMPLETENESS",
    "PERMITTED_USE",
    "PROVENANCE",
    "PROVIDER_IDENTITY_AUTHENTICATION",
    "RAW_ADJUSTED_PRICE_SEMANTICS",
    "REPRODUCIBILITY",
    "REVISION_CORRECTION_BEHAVIOR",
    "SPINOFF_ALLOCATION_EVIDENCE",
    "SPLIT_REVERSE_SPLIT_EVIDENCE",
    "SYMBOL_CHANGE_HANDLING",
    "SYMBOL_UNIVERSE_COVERAGE",
    "TRADING_DATE_CALENDAR_COMPATIBILITY",
    "UNSUPPORTED_LIFECYCLE_DETECTION",
)
_CAPABILITY_IDS = frozenset(STABLE_CAPABILITY_IDS)
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")


class QualificationSchemaError(ValueError):
    """Stable error boundary for malformed RFC-006 schema content."""


class QualificationSchemaVersionError(QualificationSchemaError):
    """Raised when a schema reader does not support the declared version."""


class QualificationSchemaValidationError(QualificationSchemaError):
    """Raised when schema content violates a structural invariant."""


class QualificationIdentityError(QualificationSchemaValidationError):
    """Raised when supplied content does not match its deterministic identity."""


class CapabilitySupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class EvidenceAssessmentStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    PARTIAL = "PARTIAL"
    UNSUITABLE = "UNSUITABLE"
    UNKNOWN = "UNKNOWN"


class RequirementClassification(str, Enum):
    REQUIRED = "Required"
    CONDITIONAL = "Conditional"
    FUTURE = "Future"


class RequestedOperationalStatus(str, Enum):
    QUALIFIED_FOR_RESEARCH = "QUALIFIED_FOR_RESEARCH"
    QUALIFIED_FOR_DAILY_PAPER_OPERATION = (
        "QUALIFIED_FOR_DAILY_PAPER_OPERATION"
    )


class ApplicabilityOutcome(str, Enum):
    APPLIES = "APPLIES"
    DOES_NOT_APPLY = "DOES_NOT_APPLY"
    UNKNOWN = "UNKNOWN"


class RequirementDecisionStatus(str, Enum):
    SATISFIED = "SATISFIED"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_ACTIVATED = "NOT_ACTIVATED"


class QualificationDecisionOutcome(str, Enum):
    QUALIFIED = "QUALIFIED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class EvidenceCoverage:
    market: str
    asset_type: str
    symbols: tuple[str, ...] = ()
    universe_identity: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    permitted_uses: tuple[str, ...] = ()
    provider_contract_identity: str | None = None
    limitation_boundaries: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "market", _required_text(self.market, "market"))
        object.__setattr__(
            self, "asset_type", _required_text(self.asset_type, "asset_type")
        )
        object.__setattr__(self, "symbols", _symbols(self.symbols))
        object.__setattr__(
            self,
            "universe_identity",
            _optional_text(self.universe_identity, "universe_identity"),
        )
        if not self.symbols and self.universe_identity is None:
            raise QualificationSchemaValidationError(
                "coverage requires symbols or universe_identity."
            )
        start = _optional_date(self.start_date, "start_date")
        end = _optional_date(self.end_date, "end_date")
        if (start is None) != (end is None):
            raise QualificationSchemaValidationError(
                "coverage start_date and end_date must be supplied together."
            )
        if start is not None and start > end:
            raise QualificationSchemaValidationError(
                "coverage start_date must not be after end_date."
            )
        object.__setattr__(self, "start_date", start)
        object.__setattr__(self, "end_date", end)
        permitted_uses = _text_tuple(self.permitted_uses, "permitted_uses")
        if not permitted_uses:
            raise QualificationSchemaValidationError(
                "coverage requires at least one permitted use."
            )
        object.__setattr__(self, "permitted_uses", permitted_uses)
        object.__setattr__(
            self,
            "provider_contract_identity",
            _optional_text(
                self.provider_contract_identity, "provider_contract_identity"
            ),
        )
        object.__setattr__(
            self,
            "limitation_boundaries",
            _text_tuple(self.limitation_boundaries, "limitation_boundaries"),
        )

    def to_representation(self):
        return {
            "asset_type": self.asset_type,
            "end_date": _date_text(self.end_date),
            "limitation_boundaries": list(self.limitation_boundaries),
            "market": self.market,
            "permitted_uses": list(self.permitted_uses),
            "provider_contract_identity": self.provider_contract_identity,
            "start_date": _date_text(self.start_date),
            "symbols": list(self.symbols),
            "universe_identity": self.universe_identity,
        }

    @classmethod
    def from_representation(cls, value):
        value = _object(value, "coverage")
        _fields(
            value,
            "coverage",
            {
                "asset_type",
                "end_date",
                "limitation_boundaries",
                "market",
                "permitted_uses",
                "provider_contract_identity",
                "start_date",
                "symbols",
                "universe_identity",
            },
        )
        return cls(
            market=value["market"],
            asset_type=value["asset_type"],
            symbols=_array(value["symbols"], "coverage.symbols"),
            universe_identity=value["universe_identity"],
            start_date=_parse_optional_date(value["start_date"], "start_date"),
            end_date=_parse_optional_date(value["end_date"], "end_date"),
            permitted_uses=_array(
                value["permitted_uses"], "coverage.permitted_uses"
            ),
            provider_contract_identity=value["provider_contract_identity"],
            limitation_boundaries=_array(
                value["limitation_boundaries"],
                "coverage.limitation_boundaries",
            ),
        )


@dataclass(frozen=True)
class ProviderCapabilityEvidence:
    capability_id: str
    provider_id: str
    adapter_version: str
    support_status: CapabilitySupportStatus
    evidence_assessment: EvidenceAssessmentStatus
    coverage: EvidenceCoverage
    evidence_references: tuple[str, ...]
    assessed_at: datetime
    limitations: tuple[str, ...] = ()
    supersedes: str | None = None
    schema_version: str = EVIDENCE_SCHEMA_VERSION
    evidence_id: str | None = field(default=None, compare=True)

    def __post_init__(self):
        _version(self.schema_version, EVIDENCE_SCHEMA_VERSION)
        object.__setattr__(
            self, "capability_id", _capability_id(self.capability_id)
        )
        object.__setattr__(
            self, "provider_id", _required_text(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self,
            "adapter_version",
            _required_text(self.adapter_version, "adapter_version"),
        )
        object.__setattr__(
            self,
            "support_status",
            _enum(CapabilitySupportStatus, self.support_status, "support_status"),
        )
        object.__setattr__(
            self,
            "evidence_assessment",
            _enum(
                EvidenceAssessmentStatus,
                self.evidence_assessment,
                "evidence_assessment",
            ),
        )
        if not isinstance(self.coverage, EvidenceCoverage):
            raise QualificationSchemaValidationError(
                "coverage must be EvidenceCoverage."
            )
        references = _text_tuple(self.evidence_references, "evidence_references")
        if not references:
            raise QualificationSchemaValidationError(
                "evidence_references must not be empty."
            )
        object.__setattr__(self, "evidence_references", references)
        object.__setattr__(
            self, "assessed_at", _utc_datetime(self.assessed_at, "assessed_at")
        )
        object.__setattr__(
            self, "limitations", _text_tuple(self.limitations, "limitations")
        )
        object.__setattr__(
            self, "supersedes", _optional_text(self.supersedes, "supersedes")
        )
        expected = canonical_identity(EVIDENCE_SCHEMA_VERSION, self._hash_payload())
        _identity(self.evidence_id, expected, "evidence_id")
        object.__setattr__(self, "evidence_id", expected)

    def _hash_payload(self):
        return self._representation(include_identity=False)

    def _representation(self, *, include_identity):
        result = {
            "adapter_version": self.adapter_version,
            "assessed_at": self.assessed_at,
            "capability_id": self.capability_id,
            "coverage": self.coverage.to_representation(),
            "evidence_assessment": self.evidence_assessment.value,
            "evidence_references": list(self.evidence_references),
            "limitations": list(self.limitations),
            "provider_id": self.provider_id,
            "schema_version": self.schema_version,
            "support_status": self.support_status.value,
            "supersedes": self.supersedes,
        }
        if include_identity:
            result["evidence_id"] = self.evidence_id
        return result

    def to_representation(self):
        return self._representation(include_identity=True)

    def to_bytes(self):
        return canonical_json_bytes(self.to_representation())

    @classmethod
    def from_representation(cls, value):
        value = _object(value, "provider capability evidence")
        _fields(
            value,
            "provider capability evidence",
            {
                "adapter_version",
                "assessed_at",
                "capability_id",
                "coverage",
                "evidence_assessment",
                "evidence_id",
                "evidence_references",
                "limitations",
                "provider_id",
                "schema_version",
                "support_status",
                "supersedes",
            },
        )
        return cls(
            schema_version=value["schema_version"],
            capability_id=value["capability_id"],
            provider_id=value["provider_id"],
            adapter_version=value["adapter_version"],
            support_status=value["support_status"],
            evidence_assessment=value["evidence_assessment"],
            coverage=EvidenceCoverage.from_representation(value["coverage"]),
            limitations=_array(value["limitations"], "limitations"),
            evidence_references=_array(
                value["evidence_references"], "evidence_references"
            ),
            assessed_at=_parse_datetime(value["assessed_at"], "assessed_at"),
            supersedes=value["supersedes"],
            evidence_id=value["evidence_id"],
        )


@dataclass(frozen=True)
class ProviderCapabilityCatalogue:
    provider_id: str
    adapter_version: str
    catalogue_evidence_version: str
    evidence_records: tuple[ProviderCapabilityEvidence, ...]
    creation_metadata: tuple[tuple[str, str], ...] = ()
    schema_version: str = CATALOGUE_SCHEMA_VERSION
    catalogue_fingerprint: str | None = field(default=None, compare=True)

    def __post_init__(self):
        _version(self.schema_version, CATALOGUE_SCHEMA_VERSION)
        object.__setattr__(
            self, "provider_id", _required_text(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self,
            "adapter_version",
            _required_text(self.adapter_version, "adapter_version"),
        )
        object.__setattr__(
            self,
            "catalogue_evidence_version",
            _required_text(
                self.catalogue_evidence_version, "catalogue_evidence_version"
            ),
        )
        records = tuple(self.evidence_records)
        if any(not isinstance(item, ProviderCapabilityEvidence) for item in records):
            raise QualificationSchemaValidationError(
                "evidence_records must contain ProviderCapabilityEvidence."
            )
        records = tuple(sorted(records, key=lambda item: item.capability_id))
        if len({item.capability_id for item in records}) != len(records):
            raise QualificationSchemaValidationError(
                "catalogue contains duplicate active capability records."
            )
        for item in records:
            if (
                item.provider_id != self.provider_id
                or item.adapter_version != self.adapter_version
            ):
                raise QualificationSchemaValidationError(
                    "catalogue evidence provider and adapter must match catalogue."
                )
        object.__setattr__(self, "evidence_records", records)
        object.__setattr__(
            self,
            "creation_metadata",
            _metadata(self.creation_metadata, "creation_metadata"),
        )
        expected = canonical_fingerprint(self._hash_payload())
        _identity(
            self.catalogue_fingerprint, expected, "catalogue_fingerprint"
        )
        object.__setattr__(self, "catalogue_fingerprint", expected)

    def _hash_payload(self):
        return self._representation(include_identity=False)

    def _representation(self, *, include_identity):
        result = {
            "adapter_version": self.adapter_version,
            "catalogue_evidence_version": self.catalogue_evidence_version,
            "creation_metadata": dict(self.creation_metadata),
            "evidence_records": [item.to_representation() for item in self.evidence_records],
            "provider_id": self.provider_id,
            "schema_version": self.schema_version,
        }
        if include_identity:
            result["catalogue_fingerprint"] = self.catalogue_fingerprint
        return result

    def to_representation(self):
        return self._representation(include_identity=True)

    def to_bytes(self):
        return canonical_json_bytes(self.to_representation())

    @classmethod
    def from_representation(cls, value):
        value = _object(value, "provider capability catalogue")
        _fields(
            value,
            "provider capability catalogue",
            {
                "adapter_version",
                "catalogue_evidence_version",
                "catalogue_fingerprint",
                "creation_metadata",
                "evidence_records",
                "provider_id",
                "schema_version",
            },
        )
        metadata = _object(value["creation_metadata"], "creation_metadata")
        return cls(
            schema_version=value["schema_version"],
            provider_id=value["provider_id"],
            adapter_version=value["adapter_version"],
            catalogue_evidence_version=value["catalogue_evidence_version"],
            evidence_records=tuple(
                ProviderCapabilityEvidence.from_representation(item)
                for item in _array(value["evidence_records"], "evidence_records")
            ),
            creation_metadata=tuple(metadata.items()),
            catalogue_fingerprint=value["catalogue_fingerprint"],
        )


@dataclass(frozen=True)
class QualificationRequirement:
    capability_id: str
    classification: RequirementClassification
    consumers: tuple[str, ...] = ()
    purpose: str | None = None
    acceptance_policy_id: str | None = None
    applicability_policy_id: str | None = None
    future_consumer: str | None = None

    def __post_init__(self):
        object.__setattr__(
            self, "capability_id", _capability_id(self.capability_id)
        )
        classification = _enum(
            RequirementClassification, self.classification, "classification"
        )
        object.__setattr__(self, "classification", classification)
        consumers = _text_tuple(self.consumers, "consumers")
        purpose = _optional_text(self.purpose, "purpose")
        acceptance = _optional_text(
            self.acceptance_policy_id, "acceptance_policy_id"
        )
        applicability = _optional_text(
            self.applicability_policy_id, "applicability_policy_id"
        )
        future_consumer = _optional_text(self.future_consumer, "future_consumer")
        if classification is RequirementClassification.REQUIRED:
            if not consumers or purpose is None or acceptance is None:
                raise QualificationSchemaValidationError(
                    "Required requirement needs consumers, purpose, and acceptance policy."
                )
            if applicability is not None or future_consumer is not None:
                raise QualificationSchemaValidationError(
                    "Required requirement cannot define applicability or future consumer."
                )
        elif classification is RequirementClassification.CONDITIONAL:
            if (
                not consumers
                or purpose is None
                or acceptance is None
                or applicability is None
            ):
                raise QualificationSchemaValidationError(
                    "Conditional requirement needs consumers, purpose, "
                    "acceptance, and applicability policies."
                )
            if future_consumer is not None:
                raise QualificationSchemaValidationError(
                    "Conditional requirement cannot define future consumer."
                )
        else:
            if future_consumer is None:
                raise QualificationSchemaValidationError(
                    "Future requirement needs a future consumer or capability."
                )
            if acceptance is not None or applicability is not None:
                raise QualificationSchemaValidationError(
                    "Future requirement cannot define active policies."
                )
        object.__setattr__(self, "consumers", consumers)
        object.__setattr__(self, "purpose", purpose)
        object.__setattr__(self, "acceptance_policy_id", acceptance)
        object.__setattr__(self, "applicability_policy_id", applicability)
        object.__setattr__(self, "future_consumer", future_consumer)

    def to_representation(self):
        return {
            "acceptance_policy_id": self.acceptance_policy_id,
            "applicability_policy_id": self.applicability_policy_id,
            "capability_id": self.capability_id,
            "classification": self.classification.value,
            "consumers": list(self.consumers),
            "future_consumer": self.future_consumer,
            "purpose": self.purpose,
        }

    @classmethod
    def from_representation(cls, value):
        value = _object(value, "qualification requirement")
        _fields(
            value,
            "qualification requirement",
            {
                "acceptance_policy_id",
                "applicability_policy_id",
                "capability_id",
                "classification",
                "consumers",
                "future_consumer",
                "purpose",
            },
        )
        return cls(
            capability_id=value["capability_id"],
            classification=value["classification"],
            consumers=_array(value["consumers"], "consumers"),
            purpose=value["purpose"],
            acceptance_policy_id=value["acceptance_policy_id"],
            applicability_policy_id=value["applicability_policy_id"],
            future_consumer=value["future_consumer"],
        )


@dataclass(frozen=True)
class OperationQualificationProfile:
    profile_id: str
    profile_version: int
    requested_operational_status: RequestedOperationalStatus
    operation_scope: str
    market: str
    asset_type: str
    requirements: tuple[QualificationRequirement, ...]
    schema_version: str = PROFILE_SCHEMA_VERSION
    profile_fingerprint: str | None = field(default=None, compare=True)

    def __post_init__(self):
        _version(self.schema_version, PROFILE_SCHEMA_VERSION)
        object.__setattr__(
            self, "profile_id", _required_text(self.profile_id, "profile_id")
        )
        if not isinstance(self.profile_version, int) or isinstance(
            self.profile_version, bool
        ) or self.profile_version < 1:
            raise QualificationSchemaValidationError(
                "profile_version must be a positive integer."
            )
        object.__setattr__(
            self,
            "requested_operational_status",
            _enum(
                RequestedOperationalStatus,
                self.requested_operational_status,
                "requested_operational_status",
            ),
        )
        object.__setattr__(
            self,
            "operation_scope",
            _required_text(self.operation_scope, "operation_scope"),
        )
        object.__setattr__(self, "market", _required_text(self.market, "market"))
        object.__setattr__(
            self, "asset_type", _required_text(self.asset_type, "asset_type")
        )
        requirements = tuple(self.requirements)
        if any(not isinstance(item, QualificationRequirement) for item in requirements):
            raise QualificationSchemaValidationError(
                "requirements must contain QualificationRequirement."
            )
        requirements = tuple(sorted(requirements, key=lambda item: item.capability_id))
        if len({item.capability_id for item in requirements}) != len(requirements):
            raise QualificationSchemaValidationError(
                "profile contains duplicate capability requirements."
            )
        if not requirements:
            raise QualificationSchemaValidationError(
                "profile requires at least one capability requirement."
            )
        object.__setattr__(self, "requirements", requirements)
        expected = canonical_fingerprint(self._hash_payload())
        _identity(self.profile_fingerprint, expected, "profile_fingerprint")
        object.__setattr__(self, "profile_fingerprint", expected)

    def _hash_payload(self):
        return self._representation(include_identity=False)

    def _representation(self, *, include_identity):
        result = {
            "asset_type": self.asset_type,
            "market": self.market,
            "operation_scope": self.operation_scope,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "requested_operational_status": self.requested_operational_status.value,
            "requirements": [item.to_representation() for item in self.requirements],
            "schema_version": self.schema_version,
        }
        if include_identity:
            result["profile_fingerprint"] = self.profile_fingerprint
        return result

    def to_representation(self):
        return self._representation(include_identity=True)

    def to_bytes(self):
        return canonical_json_bytes(self.to_representation())

    @classmethod
    def from_representation(cls, value):
        value = _object(value, "operation qualification profile")
        _fields(
            value,
            "operation qualification profile",
            {
                "asset_type",
                "market",
                "operation_scope",
                "profile_fingerprint",
                "profile_id",
                "profile_version",
                "requested_operational_status",
                "requirements",
                "schema_version",
            },
        )
        return cls(
            schema_version=value["schema_version"],
            profile_id=value["profile_id"],
            profile_version=value["profile_version"],
            requested_operational_status=value["requested_operational_status"],
            operation_scope=value["operation_scope"],
            market=value["market"],
            asset_type=value["asset_type"],
            requirements=tuple(
                QualificationRequirement.from_representation(item)
                for item in _array(value["requirements"], "requirements")
            ),
            profile_fingerprint=value["profile_fingerprint"],
        )


@dataclass(frozen=True)
class QualificationScope:
    provider_id: str
    adapter_version: str
    profile_id: str
    profile_version: int
    market: str
    asset_type: str
    permitted_use_identity: str
    symbols: tuple[str, ...] = ()
    universe_identity: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    provider_contract_identity: str | None = None

    def __post_init__(self):
        for name in (
            "provider_id",
            "adapter_version",
            "profile_id",
            "market",
            "asset_type",
            "permitted_use_identity",
        ):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        if not isinstance(self.profile_version, int) or isinstance(
            self.profile_version, bool
        ) or self.profile_version < 1:
            raise QualificationSchemaValidationError(
                "profile_version must be a positive integer."
            )
        object.__setattr__(self, "symbols", _symbols(self.symbols))
        object.__setattr__(
            self,
            "universe_identity",
            _optional_text(self.universe_identity, "universe_identity"),
        )
        if not self.symbols and self.universe_identity is None:
            raise QualificationSchemaValidationError(
                "scope requires symbols or universe_identity."
            )
        start = _optional_date(self.start_date, "start_date")
        end = _optional_date(self.end_date, "end_date")
        if (start is None) != (end is None):
            raise QualificationSchemaValidationError(
                "scope start_date and end_date must be supplied together."
            )
        if start is not None and start > end:
            raise QualificationSchemaValidationError(
                "scope start_date must not be after end_date."
            )
        object.__setattr__(self, "start_date", start)
        object.__setattr__(self, "end_date", end)
        object.__setattr__(
            self,
            "provider_contract_identity",
            _optional_text(
                self.provider_contract_identity, "provider_contract_identity"
            ),
        )

    @property
    def scope_identity(self):
        return canonical_fingerprint(self.to_representation())

    def to_representation(self):
        return {
            "adapter_version": self.adapter_version,
            "asset_type": self.asset_type,
            "end_date": _date_text(self.end_date),
            "market": self.market,
            "permitted_use_identity": self.permitted_use_identity,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "provider_contract_identity": self.provider_contract_identity,
            "provider_id": self.provider_id,
            "start_date": _date_text(self.start_date),
            "symbols": list(self.symbols),
            "universe_identity": self.universe_identity,
        }

    @classmethod
    def from_representation(cls, value):
        value = _object(value, "qualification scope")
        _fields(
            value,
            "qualification scope",
            {
                "adapter_version",
                "asset_type",
                "end_date",
                "market",
                "permitted_use_identity",
                "profile_id",
                "profile_version",
                "provider_contract_identity",
                "provider_id",
                "start_date",
                "symbols",
                "universe_identity",
            },
        )
        return cls(
            provider_id=value["provider_id"],
            adapter_version=value["adapter_version"],
            profile_id=value["profile_id"],
            profile_version=value["profile_version"],
            market=value["market"],
            asset_type=value["asset_type"],
            symbols=_array(value["symbols"], "scope.symbols"),
            universe_identity=value["universe_identity"],
            start_date=_parse_optional_date(value["start_date"], "start_date"),
            end_date=_parse_optional_date(value["end_date"], "end_date"),
            permitted_use_identity=value["permitted_use_identity"],
            provider_contract_identity=value["provider_contract_identity"],
        )


@dataclass(frozen=True)
class ApplicabilityEvidence:
    capability_id: str
    applicability_policy_id: str
    outcome: ApplicabilityOutcome
    scope_identity: str
    evidence_references: tuple[str, ...]
    safe_reason: str
    fingerprint: str | None = field(default=None, compare=True)

    def __post_init__(self):
        object.__setattr__(
            self, "capability_id", _capability_id(self.capability_id)
        )
        object.__setattr__(
            self,
            "applicability_policy_id",
            _required_text(
                self.applicability_policy_id, "applicability_policy_id"
            ),
        )
        object.__setattr__(
            self,
            "outcome",
            _enum(ApplicabilityOutcome, self.outcome, "outcome"),
        )
        scope_identity = _required_text(self.scope_identity, "scope_identity")
        if not _FINGERPRINT.fullmatch(scope_identity):
            raise QualificationSchemaValidationError(
                "scope_identity must be a sha256 fingerprint."
            )
        object.__setattr__(self, "scope_identity", scope_identity)
        references = _text_tuple(self.evidence_references, "evidence_references")
        if not references:
            raise QualificationSchemaValidationError(
                "applicability evidence requires evidence references."
            )
        object.__setattr__(self, "evidence_references", references)
        object.__setattr__(
            self, "safe_reason", _required_text(self.safe_reason, "safe_reason")
        )
        expected = canonical_fingerprint(self._hash_payload())
        _identity(self.fingerprint, expected, "fingerprint")
        object.__setattr__(self, "fingerprint", expected)

    def _hash_payload(self):
        return self._representation(include_identity=False)

    def _representation(self, *, include_identity):
        result = {
            "applicability_policy_id": self.applicability_policy_id,
            "capability_id": self.capability_id,
            "evidence_references": list(self.evidence_references),
            "outcome": self.outcome.value,
            "safe_reason": self.safe_reason,
            "scope_identity": self.scope_identity,
        }
        if include_identity:
            result["fingerprint"] = self.fingerprint
        return result

    def to_representation(self):
        return self._representation(include_identity=True)

    @classmethod
    def from_representation(cls, value):
        value = _object(value, "applicability evidence")
        _fields(
            value,
            "applicability evidence",
            {
                "applicability_policy_id",
                "capability_id",
                "evidence_references",
                "fingerprint",
                "outcome",
                "safe_reason",
                "scope_identity",
            },
        )
        return cls(
            capability_id=value["capability_id"],
            applicability_policy_id=value["applicability_policy_id"],
            outcome=value["outcome"],
            scope_identity=value["scope_identity"],
            evidence_references=_array(
                value["evidence_references"], "evidence_references"
            ),
            safe_reason=value["safe_reason"],
            fingerprint=value["fingerprint"],
        )


@dataclass(frozen=True)
class RequirementDecisionResult:
    capability_id: str
    classification: RequirementClassification
    status: RequirementDecisionStatus
    safe_summary: str
    applicability_outcome: ApplicabilityOutcome | None = None
    acceptance_policy_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    blocking_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(
            self, "capability_id", _capability_id(self.capability_id)
        )
        object.__setattr__(
            self,
            "classification",
            _enum(
                RequirementClassification, self.classification, "classification"
            ),
        )
        object.__setattr__(
            self,
            "status",
            _enum(RequirementDecisionStatus, self.status, "status"),
        )
        applicability = self.applicability_outcome
        if applicability is not None:
            applicability = _enum(
                ApplicabilityOutcome, applicability, "applicability_outcome"
            )
        object.__setattr__(self, "applicability_outcome", applicability)
        object.__setattr__(
            self,
            "acceptance_policy_id",
            _optional_text(self.acceptance_policy_id, "acceptance_policy_id"),
        )
        object.__setattr__(
            self, "evidence_ids", _text_tuple(self.evidence_ids, "evidence_ids")
        )
        object.__setattr__(
            self, "safe_summary", _required_text(self.safe_summary, "safe_summary")
        )
        object.__setattr__(
            self,
            "blocking_reasons",
            _text_tuple(self.blocking_reasons, "blocking_reasons"),
        )
        object.__setattr__(
            self, "warnings", _text_tuple(self.warnings, "warnings")
        )

    def to_representation(self):
        return {
            "acceptance_policy_id": self.acceptance_policy_id,
            "applicability_outcome": (
                self.applicability_outcome.value
                if self.applicability_outcome is not None
                else None
            ),
            "blocking_reasons": list(self.blocking_reasons),
            "capability_id": self.capability_id,
            "classification": self.classification.value,
            "evidence_ids": list(self.evidence_ids),
            "safe_summary": self.safe_summary,
            "status": self.status.value,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_representation(cls, value):
        value = _object(value, "requirement decision result")
        _fields(
            value,
            "requirement decision result",
            {
                "acceptance_policy_id",
                "applicability_outcome",
                "blocking_reasons",
                "capability_id",
                "classification",
                "evidence_ids",
                "safe_summary",
                "status",
                "warnings",
            },
        )
        return cls(
            capability_id=value["capability_id"],
            classification=value["classification"],
            status=value["status"],
            applicability_outcome=value["applicability_outcome"],
            acceptance_policy_id=value["acceptance_policy_id"],
            evidence_ids=_array(value["evidence_ids"], "evidence_ids"),
            safe_summary=value["safe_summary"],
            blocking_reasons=_array(
                value["blocking_reasons"], "blocking_reasons"
            ),
            warnings=_array(value["warnings"], "warnings"),
        )


@dataclass(frozen=True)
class QualificationDecision:
    provider_id: str
    adapter_version: str
    profile_id: str
    profile_version: int
    profile_fingerprint: str
    evidence_schema_versions: tuple[str, ...]
    catalogue_schema_version: str
    profile_schema_version: str
    requested_operational_status: RequestedOperationalStatus
    scope: QualificationScope
    catalogue_fingerprint: str
    applicability_evidence_fingerprints: tuple[str, ...]
    requirement_results: tuple[RequirementDecisionResult, ...]
    overall_outcome: QualificationDecisionOutcome
    blocking_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    evaluated_evidence_ids: tuple[str, ...] = ()
    schema_version: str = DECISION_SCHEMA_VERSION
    decision_id: str | None = field(default=None, compare=True)
    decision_fingerprint: str | None = field(default=None, compare=True)

    def __post_init__(self):
        _version(self.schema_version, DECISION_SCHEMA_VERSION)
        for name in ("provider_id", "adapter_version", "profile_id"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        if not isinstance(self.profile_version, int) or isinstance(
            self.profile_version, bool
        ) or self.profile_version < 1:
            raise QualificationSchemaValidationError(
                "profile_version must be a positive integer."
            )
        for name in (
            "profile_fingerprint",
            "catalogue_fingerprint",
        ):
            value = _required_text(getattr(self, name), name)
            if not _FINGERPRINT.fullmatch(value):
                raise QualificationSchemaValidationError(
                    f"{name} must be a sha256 fingerprint."
                )
            object.__setattr__(self, name, value)
        versions = _text_tuple(
            self.evidence_schema_versions, "evidence_schema_versions"
        )
        if not versions:
            raise QualificationSchemaValidationError(
                "decision requires evidence_schema_versions."
            )
        if any(version != EVIDENCE_SCHEMA_VERSION for version in versions):
            raise QualificationSchemaVersionError(
                "Decision references an unsupported evidence schema version."
            )
        object.__setattr__(self, "evidence_schema_versions", versions)
        _version(self.catalogue_schema_version, CATALOGUE_SCHEMA_VERSION)
        _version(self.profile_schema_version, PROFILE_SCHEMA_VERSION)
        object.__setattr__(
            self,
            "requested_operational_status",
            _enum(
                RequestedOperationalStatus,
                self.requested_operational_status,
                "requested_operational_status",
            ),
        )
        if not isinstance(self.scope, QualificationScope):
            raise QualificationSchemaValidationError(
                "scope must be QualificationScope."
            )
        if (
            self.scope.provider_id != self.provider_id
            or self.scope.adapter_version != self.adapter_version
            or self.scope.profile_id != self.profile_id
            or self.scope.profile_version != self.profile_version
        ):
            raise QualificationSchemaValidationError(
                "decision identity fields must match qualification scope."
            )
        applicability = _fingerprints(
            self.applicability_evidence_fingerprints,
            "applicability_evidence_fingerprints",
        )
        object.__setattr__(
            self, "applicability_evidence_fingerprints", applicability
        )
        results = tuple(self.requirement_results)
        if any(not isinstance(item, RequirementDecisionResult) for item in results):
            raise QualificationSchemaValidationError(
                "requirement_results must contain RequirementDecisionResult."
            )
        results = tuple(sorted(results, key=lambda item: item.capability_id))
        if len({item.capability_id for item in results}) != len(results):
            raise QualificationSchemaValidationError(
                "decision contains duplicate requirement results."
            )
        object.__setattr__(self, "requirement_results", results)
        object.__setattr__(
            self,
            "overall_outcome",
            _enum(
                QualificationDecisionOutcome,
                self.overall_outcome,
                "overall_outcome",
            ),
        )
        object.__setattr__(
            self,
            "blocking_reasons",
            _text_tuple(self.blocking_reasons, "blocking_reasons"),
        )
        object.__setattr__(
            self, "warnings", _text_tuple(self.warnings, "warnings")
        )
        object.__setattr__(
            self,
            "evaluated_evidence_ids",
            _text_tuple(self.evaluated_evidence_ids, "evaluated_evidence_ids"),
        )
        digest_identity = canonical_identity(
            DECISION_SCHEMA_VERSION, self._hash_payload()
        )
        digest = digest_identity.removeprefix(f"{DECISION_SCHEMA_VERSION}:")
        expected_fingerprint = f"sha256:{digest}"
        _identity(self.decision_id, digest_identity, "decision_id")
        _identity(
            self.decision_fingerprint,
            expected_fingerprint,
            "decision_fingerprint",
        )
        object.__setattr__(self, "decision_id", digest_identity)
        object.__setattr__(self, "decision_fingerprint", expected_fingerprint)

    def _hash_payload(self):
        return {
            "applicability_evidence_fingerprints": list(
                self.applicability_evidence_fingerprints
            ),
            "catalogue_fingerprint": self.catalogue_fingerprint,
            "profile_fingerprint": self.profile_fingerprint,
            "requirement_results": [
                item.to_representation() for item in self.requirement_results
            ],
            "schema_version": self.schema_version,
            "scope": self.scope.to_representation(),
        }

    def _representation(self, *, include_identity):
        result = {
            "adapter_version": self.adapter_version,
            "applicability_evidence_fingerprints": list(
                self.applicability_evidence_fingerprints
            ),
            "blocking_reasons": list(self.blocking_reasons),
            "catalogue_fingerprint": self.catalogue_fingerprint,
            "catalogue_schema_version": self.catalogue_schema_version,
            "evaluated_evidence_ids": list(self.evaluated_evidence_ids),
            "evidence_schema_versions": list(self.evidence_schema_versions),
            "overall_outcome": self.overall_outcome.value,
            "profile_fingerprint": self.profile_fingerprint,
            "profile_id": self.profile_id,
            "profile_schema_version": self.profile_schema_version,
            "profile_version": self.profile_version,
            "provider_id": self.provider_id,
            "requested_operational_status": self.requested_operational_status.value,
            "requirement_results": [
                item.to_representation() for item in self.requirement_results
            ],
            "schema_version": self.schema_version,
            "scope": self.scope.to_representation(),
            "warnings": list(self.warnings),
        }
        if include_identity:
            result["decision_fingerprint"] = self.decision_fingerprint
            result["decision_id"] = self.decision_id
        return result

    def to_representation(self):
        return self._representation(include_identity=True)

    def to_bytes(self):
        return canonical_json_bytes(self.to_representation())

    @classmethod
    def from_representation(cls, value):
        value = _object(value, "provider qualification decision")
        _fields(
            value,
            "provider qualification decision",
            {
                "adapter_version",
                "applicability_evidence_fingerprints",
                "blocking_reasons",
                "catalogue_fingerprint",
                "catalogue_schema_version",
                "decision_fingerprint",
                "decision_id",
                "evaluated_evidence_ids",
                "evidence_schema_versions",
                "overall_outcome",
                "profile_fingerprint",
                "profile_id",
                "profile_schema_version",
                "profile_version",
                "provider_id",
                "requested_operational_status",
                "requirement_results",
                "schema_version",
                "scope",
                "warnings",
            },
        )
        return cls(
            schema_version=value["schema_version"],
            decision_id=value["decision_id"],
            decision_fingerprint=value["decision_fingerprint"],
            provider_id=value["provider_id"],
            adapter_version=value["adapter_version"],
            profile_id=value["profile_id"],
            profile_version=value["profile_version"],
            profile_fingerprint=value["profile_fingerprint"],
            evidence_schema_versions=_array(
                value["evidence_schema_versions"], "evidence_schema_versions"
            ),
            catalogue_schema_version=value["catalogue_schema_version"],
            profile_schema_version=value["profile_schema_version"],
            requested_operational_status=value["requested_operational_status"],
            scope=QualificationScope.from_representation(value["scope"]),
            catalogue_fingerprint=value["catalogue_fingerprint"],
            applicability_evidence_fingerprints=_array(
                value["applicability_evidence_fingerprints"],
                "applicability_evidence_fingerprints",
            ),
            requirement_results=tuple(
                RequirementDecisionResult.from_representation(item)
                for item in _array(
                    value["requirement_results"], "requirement_results"
                )
            ),
            overall_outcome=value["overall_outcome"],
            blocking_reasons=_array(
                value["blocking_reasons"], "blocking_reasons"
            ),
            warnings=_array(value["warnings"], "warnings"),
            evaluated_evidence_ids=_array(
                value["evaluated_evidence_ids"], "evaluated_evidence_ids"
            ),
        )


def serialize_qualification_schema(value):
    if not isinstance(
        value,
        (
            ProviderCapabilityEvidence,
            ProviderCapabilityCatalogue,
            OperationQualificationProfile,
            QualificationDecision,
        ),
    ):
        raise TypeError("value must be a canonical RFC-006 top-level schema.")
    return value.to_bytes()


def deserialize_provider_capability_evidence(payload):
    return ProviderCapabilityEvidence.from_representation(parse_json_payload(payload))


def deserialize_provider_capability_catalogue(payload):
    return ProviderCapabilityCatalogue.from_representation(parse_json_payload(payload))


def deserialize_operation_qualification_profile(payload):
    return OperationQualificationProfile.from_representation(parse_json_payload(payload))


def deserialize_provider_qualification_decision(payload):
    return QualificationDecision.from_representation(parse_json_payload(payload))


def _required_text(value, field_name):
    if not isinstance(value, str):
        raise QualificationSchemaValidationError(f"{field_name} must be text.")
    value = unicodedata.normalize("NFC", value).strip()
    if not value:
        raise QualificationSchemaValidationError(f"{field_name} must not be empty.")
    return value


def _optional_text(value, field_name):
    if value is None:
        return None
    return _required_text(value, field_name)


def _text_tuple(values, field_name):
    if isinstance(values, (str, bytes)):
        raise QualificationSchemaValidationError(f"{field_name} must be a collection.")
    try:
        normalized = tuple(
            sorted({_required_text(item, field_name) for item in values})
        )
    except TypeError as error:
        raise QualificationSchemaValidationError(
            f"{field_name} must be an iterable of text values."
        ) from error
    return normalized


def _symbols(values):
    if isinstance(values, (str, bytes)):
        raise QualificationSchemaValidationError("symbols must be a collection.")
    try:
        return tuple(
            sorted({_required_text(value, "symbol").upper() for value in values})
        )
    except TypeError as error:
        raise QualificationSchemaValidationError(
            "symbols must be an iterable of text values."
        ) from error


def _metadata(values, field_name):
    if isinstance(values, dict):
        values = values.items()
    try:
        pairs = tuple(
            (_required_text(key, f"{field_name} key"), _required_text(value, field_name))
            for key, value in values
        )
    except (TypeError, ValueError) as error:
        raise QualificationSchemaValidationError(
            f"{field_name} must contain text key/value pairs."
        ) from error
    if len({key for key, _ in pairs}) != len(pairs):
        raise QualificationSchemaValidationError(
            f"{field_name} contains duplicate keys."
        )
    return tuple(sorted(pairs))


def _fingerprints(values, field_name):
    if isinstance(values, (str, bytes)):
        raise QualificationSchemaValidationError(
            f"{field_name} must be a collection."
        )
    try:
        values = tuple(
            _required_text(value, field_name) for value in values
        )
    except TypeError as error:
        raise QualificationSchemaValidationError(
            f"{field_name} must be an iterable of fingerprints."
        ) from error
    if len(set(values)) != len(values):
        raise QualificationSchemaValidationError(
            f"{field_name} must not contain duplicate fingerprints."
        )
    if any(not _FINGERPRINT.fullmatch(value) for value in values):
        raise QualificationSchemaValidationError(
            f"{field_name} must contain sha256 fingerprints."
        )
    return values


def _capability_id(value):
    value = _required_text(value, "capability_id")
    if value not in _CAPABILITY_IDS:
        raise QualificationSchemaValidationError(
            f"Unsupported capability_id: {value}."
        )
    return value


def _enum(enum_type, value, field_name):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        raise QualificationSchemaValidationError(
            f"Unsupported {field_name}: {value}."
        ) from error


def _version(value, expected):
    if value != expected:
        raise QualificationSchemaVersionError(
            f"Unsupported schema version {value!r}; expected {expected!r}."
        )


def _identity(actual, expected, field_name):
    if actual is not None and actual != expected:
        raise QualificationIdentityError(
            f"{field_name} does not match canonical content."
        )


def _utc_datetime(value, field_name):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise QualificationSchemaValidationError(
            f"{field_name} must be a timezone-aware datetime."
        )
    return value.astimezone(timezone.utc)


def _optional_date(value, field_name):
    if value is None:
        return None
    if not isinstance(value, date) or isinstance(value, datetime):
        raise QualificationSchemaValidationError(f"{field_name} must be a date.")
    return value


def _date_text(value):
    return value.isoformat() if value is not None else None


def _parse_optional_date(value, field_name):
    if value is None:
        return None
    if not isinstance(value, str):
        raise QualificationSchemaValidationError(f"{field_name} must be an ISO date.")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise QualificationSchemaValidationError(
            f"{field_name} must be an ISO date."
        ) from error


def _parse_datetime(value, field_name):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise QualificationSchemaValidationError(
            f"{field_name} must be an ISO-8601 UTC timestamp with Z suffix."
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise QualificationSchemaValidationError(
            f"{field_name} must be an ISO-8601 UTC timestamp with Z suffix."
        ) from error
    return _utc_datetime(parsed, field_name)


def _object(value, field_name):
    if not isinstance(value, dict):
        raise QualificationSchemaValidationError(f"{field_name} must be an object.")
    return value


def _array(value, field_name):
    if not isinstance(value, list):
        raise QualificationSchemaValidationError(f"{field_name} must be an array.")
    return tuple(value)


def _fields(value, name, expected):
    present = set(value)
    missing = sorted(expected - present)
    unknown = sorted(present - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown fields: {', '.join(unknown)}")
        raise QualificationSchemaValidationError(f"Invalid {name}: {'; '.join(details)}.")


__all__ = [
    "ApplicabilityEvidence",
    "ApplicabilityOutcome",
    "CATALOGUE_SCHEMA_VERSION",
    "CapabilitySupportStatus",
    "DECISION_SCHEMA_VERSION",
    "EVIDENCE_SCHEMA_VERSION",
    "EvidenceAssessmentStatus",
    "EvidenceCoverage",
    "OperationQualificationProfile",
    "PROFILE_SCHEMA_VERSION",
    "ProviderCapabilityCatalogue",
    "ProviderCapabilityEvidence",
    "QualificationDecision",
    "QualificationDecisionOutcome",
    "QualificationIdentityError",
    "QualificationRequirement",
    "QualificationSchemaError",
    "QualificationSchemaValidationError",
    "QualificationSchemaVersionError",
    "QualificationScope",
    "RequestedOperationalStatus",
    "RequirementClassification",
    "RequirementDecisionResult",
    "RequirementDecisionStatus",
    "STABLE_CAPABILITY_IDS",
    "STRICT_SCOPE_QUALIFIED_V1",
    "deserialize_operation_qualification_profile",
    "deserialize_provider_capability_catalogue",
    "deserialize_provider_capability_evidence",
    "deserialize_provider_qualification_decision",
    "serialize_qualification_schema",
]
