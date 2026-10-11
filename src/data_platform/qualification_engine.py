"""Pure RFC-006 operation-scoped provider qualification evaluator."""

from .qualification_schemas import (
    ApplicabilityEvidence,
    ApplicabilityOutcome,
    CATALOGUE_SCHEMA_VERSION,
    CapabilitySupportStatus,
    EVIDENCE_SCHEMA_VERSION,
    EvidenceAssessmentStatus,
    OperationQualificationProfile,
    PROFILE_SCHEMA_VERSION,
    ProviderCapabilityCatalogue,
    QualificationDecision,
    QualificationDecisionOutcome,
    QualificationSchemaValidationError,
    QualificationSchemaVersionError,
    QualificationScope,
    RequirementClassification,
    RequirementDecisionResult,
    RequirementDecisionStatus,
    STRICT_SCOPE_QUALIFIED_V1,
)


def evaluate(catalogue, profile, scope, applicability_evidence):
    """Return one deterministic RFC-006 decision for the four explicit inputs."""

    applicability = _validate_inputs(
        catalogue,
        profile,
        scope,
        applicability_evidence,
    )
    evidence_by_capability = {
        item.capability_id: item for item in catalogue.evidence_records
    }
    applicability_by_capability = {
        item.capability_id: item for item in applicability
    }
    results = []
    for requirement in profile.requirements:
        results.append(
            _evaluate_requirement(
                requirement,
                evidence_by_capability,
                scope,
                applicability_by_capability,
            )
        )

    blocking_reasons = tuple(
        reason
        for result in results
        for reason in result.blocking_reasons
    )
    warnings = tuple(
        warning for result in results for warning in result.warnings
    )
    evaluated_evidence_ids = tuple(
        evidence_id
        for result in results
        for evidence_id in result.evidence_ids
    )
    outcome = (
        QualificationDecisionOutcome.BLOCKED
        if any(
            result.status is RequirementDecisionStatus.BLOCKED
            for result in results
        )
        else QualificationDecisionOutcome.QUALIFIED
    )
    evidence_schema_versions = tuple(
        sorted({item.schema_version for item in catalogue.evidence_records})
    ) or (EVIDENCE_SCHEMA_VERSION,)

    return QualificationDecision(
        provider_id=catalogue.provider_id,
        adapter_version=catalogue.adapter_version,
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        profile_fingerprint=profile.profile_fingerprint,
        evidence_schema_versions=evidence_schema_versions,
        catalogue_schema_version=catalogue.schema_version,
        profile_schema_version=profile.schema_version,
        requested_operational_status=profile.requested_operational_status,
        scope=scope,
        catalogue_fingerprint=catalogue.catalogue_fingerprint,
        applicability_evidence_fingerprints=tuple(
            item.fingerprint for item in applicability
        ),
        requirement_results=tuple(results),
        overall_outcome=outcome,
        blocking_reasons=blocking_reasons,
        warnings=warnings,
        evaluated_evidence_ids=evaluated_evidence_ids,
    )


def _validate_inputs(catalogue, profile, scope, applicability_evidence):
    if not isinstance(catalogue, ProviderCapabilityCatalogue):
        raise QualificationSchemaValidationError(
            "catalogue must be ProviderCapabilityCatalogue."
        )
    if not isinstance(profile, OperationQualificationProfile):
        raise QualificationSchemaValidationError(
            "profile must be OperationQualificationProfile."
        )
    if not isinstance(scope, QualificationScope):
        raise QualificationSchemaValidationError(
            "scope must be QualificationScope."
        )
    if catalogue.schema_version != CATALOGUE_SCHEMA_VERSION:
        raise QualificationSchemaVersionError(
            "Unsupported capability catalogue schema version."
        )
    if profile.schema_version != PROFILE_SCHEMA_VERSION:
        raise QualificationSchemaVersionError(
            "Unsupported qualification profile schema version."
        )
    if (
        catalogue.provider_id != scope.provider_id
        or catalogue.adapter_version != scope.adapter_version
    ):
        raise QualificationSchemaValidationError(
            "catalogue provider and adapter must match scope."
        )
    if (
        profile.profile_id != scope.profile_id
        or profile.profile_version != scope.profile_version
    ):
        raise QualificationSchemaValidationError(
            "profile identity and version must match scope."
        )
    if profile.market != scope.market or profile.asset_type != scope.asset_type:
        raise QualificationSchemaValidationError(
            "profile market and asset type must match scope."
        )
    if profile.operation_scope != scope.permitted_use_identity:
        raise QualificationSchemaValidationError(
            "profile operation scope must match scope permitted use."
        )
    for requirement in profile.requirements:
        if (
            requirement.classification
            is not RequirementClassification.FUTURE
            and requirement.acceptance_policy_id
            != STRICT_SCOPE_QUALIFIED_V1
        ):
            raise QualificationSchemaValidationError(
                "Activated requirements must use STRICT_SCOPE_QUALIFIED_V1."
            )

    if isinstance(applicability_evidence, (str, bytes)):
        raise QualificationSchemaValidationError(
            "applicability_evidence must be a collection."
        )
    try:
        applicability = tuple(applicability_evidence)
    except TypeError as error:
        raise QualificationSchemaValidationError(
            "applicability_evidence must be an iterable."
        ) from error
    if any(not isinstance(item, ApplicabilityEvidence) for item in applicability):
        raise QualificationSchemaValidationError(
            "applicability_evidence must contain ApplicabilityEvidence."
        )
    if len({item.capability_id for item in applicability}) != len(applicability):
        raise QualificationSchemaValidationError(
            "applicability_evidence contains duplicate capability identities."
        )
    conditional_ids = {
        item.capability_id
        for item in profile.requirements
        if item.classification is RequirementClassification.CONDITIONAL
    }
    unexpected = sorted(
        item.capability_id
        for item in applicability
        if item.capability_id not in conditional_ids
    )
    if unexpected:
        raise QualificationSchemaValidationError(
            "Applicability evidence is only valid for profile Conditional "
            f"requirements: {', '.join(unexpected)}."
        )
    return tuple(sorted(applicability, key=lambda item: item.capability_id))


def _evaluate_requirement(
    requirement,
    evidence_by_capability,
    scope,
    applicability_by_capability,
):
    if requirement.classification is RequirementClassification.FUTURE:
        return RequirementDecisionResult(
            capability_id=requirement.capability_id,
            classification=requirement.classification,
            status=RequirementDecisionStatus.NOT_ACTIVATED,
            safe_summary=(
                f"{requirement.capability_id}: Future capability is not "
                "activated by this profile."
            ),
        )

    applicability = None
    if requirement.classification is RequirementClassification.CONDITIONAL:
        applicability = applicability_by_capability.get(requirement.capability_id)
        conditional_result = _resolve_conditional(
            requirement,
            applicability,
            scope,
        )
        if conditional_result is not None:
            return conditional_result

    evidence = evidence_by_capability.get(requirement.capability_id)
    return _evaluate_activated(
        requirement,
        evidence,
        scope,
        applicability,
    )


def _resolve_conditional(requirement, applicability, scope):
    capability_id = requirement.capability_id
    if applicability is None:
        return _blocked_result(
            requirement,
            None,
            (),
            f"{capability_id}: conditional applicability evidence is missing.",
            "Conditional applicability cannot be established.",
        )
    if applicability.applicability_policy_id != requirement.applicability_policy_id:
        return _blocked_result(
            requirement,
            applicability.outcome,
            applicability.evidence_references,
            f"{capability_id}: applicability policy does not match profile.",
            "Conditional applicability policy is incompatible.",
        )
    if applicability.scope_identity != scope.scope_identity:
        return _blocked_result(
            requirement,
            applicability.outcome,
            applicability.evidence_references,
            f"{capability_id}: applicability evidence scope does not match decision scope.",
            "Conditional applicability scope is incompatible.",
        )
    if applicability.outcome is ApplicabilityOutcome.UNKNOWN:
        return _blocked_result(
            requirement,
            applicability.outcome,
            applicability.evidence_references,
            f"{capability_id}: conditional applicability is UNKNOWN.",
            "Conditional applicability remains unknown.",
        )
    if applicability.outcome is ApplicabilityOutcome.DOES_NOT_APPLY:
        return RequirementDecisionResult(
            capability_id=capability_id,
            classification=requirement.classification,
            status=RequirementDecisionStatus.NOT_APPLICABLE,
            applicability_outcome=applicability.outcome,
            acceptance_policy_id=requirement.acceptance_policy_id,
            evidence_ids=applicability.evidence_references,
            safe_summary=(
                f"{capability_id}: accepted applicability evidence establishes "
                "DOES_NOT_APPLY."
            ),
        )
    return None


def _evaluate_activated(requirement, evidence, scope, applicability):
    capability_id = requirement.capability_id
    evidence_ids = list(
        applicability.evidence_references if applicability is not None else ()
    )
    blockers = []
    warnings = []
    if evidence is None:
        blockers.append(f"{capability_id}: active capability evidence is missing.")
    else:
        evidence_ids.append(evidence.evidence_id)
        if evidence.support_status is not CapabilitySupportStatus.SUPPORTED:
            blockers.append(
                f"{capability_id}: support status is {evidence.support_status.value}."
            )
        if evidence.evidence_assessment is not EvidenceAssessmentStatus.QUALIFIED:
            blockers.append(
                f"{capability_id}: evidence assessment is "
                f"{evidence.evidence_assessment.value}."
            )
        blockers.extend(_coverage_blockers(capability_id, evidence.coverage, scope))
        warnings.extend(_limitation_warnings(capability_id, evidence))

    if blockers:
        return RequirementDecisionResult(
            capability_id=capability_id,
            classification=requirement.classification,
            status=RequirementDecisionStatus.BLOCKED,
            applicability_outcome=(
                applicability.outcome if applicability is not None else None
            ),
            acceptance_policy_id=requirement.acceptance_policy_id,
            evidence_ids=tuple(evidence_ids),
            safe_summary=(
                f"{capability_id}: activated evidence does not satisfy "
                f"{STRICT_SCOPE_QUALIFIED_V1}."
            ),
            blocking_reasons=tuple(blockers),
            warnings=tuple(warnings),
        )
    return RequirementDecisionResult(
        capability_id=capability_id,
        classification=requirement.classification,
        status=RequirementDecisionStatus.SATISFIED,
        applicability_outcome=(
            applicability.outcome if applicability is not None else None
        ),
        acceptance_policy_id=requirement.acceptance_policy_id,
        evidence_ids=tuple(evidence_ids),
        safe_summary=(
            f"{capability_id}: activated evidence satisfies "
            f"{STRICT_SCOPE_QUALIFIED_V1}."
        ),
        warnings=tuple(warnings),
    )


def _coverage_blockers(capability_id, coverage, scope):
    blockers = []
    if coverage.market != scope.market:
        blockers.append(f"{capability_id}: evidence market does not match scope.")
    if coverage.asset_type != scope.asset_type:
        blockers.append(
            f"{capability_id}: evidence asset type does not match scope."
        )
    missing_symbols = tuple(sorted(set(scope.symbols) - set(coverage.symbols)))
    if missing_symbols:
        blockers.append(
            f"{capability_id}: evidence is missing required symbols "
            f"{','.join(missing_symbols)}."
        )
    if (
        scope.universe_identity is not None
        and coverage.universe_identity != scope.universe_identity
    ):
        blockers.append(
            f"{capability_id}: evidence universe identity does not match scope."
        )
    if scope.start_date is not None:
        if coverage.start_date is None or coverage.end_date is None:
            blockers.append(
                f"{capability_id}: evidence date coverage is unavailable."
            )
        else:
            if coverage.start_date > scope.start_date:
                blockers.append(
                    f"{capability_id}: evidence starts after the required interval."
                )
            if coverage.end_date < scope.end_date:
                blockers.append(
                    f"{capability_id}: evidence ends before the required interval."
                )
    if scope.permitted_use_identity not in coverage.permitted_uses:
        blockers.append(
            f"{capability_id}: evidence does not permit the requested operation."
        )
    if (
        scope.provider_contract_identity is not None
        and coverage.provider_contract_identity
        != scope.provider_contract_identity
    ):
        blockers.append(
            f"{capability_id}: provider contract identity does not match scope."
        )
    return tuple(blockers)


def _limitation_warnings(capability_id, evidence):
    # Structured coverage controls acceptance; disclosure text remains evidence.
    return tuple(
        [
            f"{capability_id}: disclosed limitation: {value}"
            for value in evidence.limitations
        ]
        + [
            f"{capability_id}: coverage boundary: {value}"
            for value in evidence.coverage.limitation_boundaries
        ]
    )


def _blocked_result(
    requirement,
    applicability_outcome,
    evidence_ids,
    blocking_reason,
    summary,
):
    return RequirementDecisionResult(
        capability_id=requirement.capability_id,
        classification=requirement.classification,
        status=RequirementDecisionStatus.BLOCKED,
        applicability_outcome=applicability_outcome,
        acceptance_policy_id=requirement.acceptance_policy_id,
        evidence_ids=tuple(evidence_ids),
        safe_summary=f"{requirement.capability_id}: {summary}",
        blocking_reasons=(blocking_reason,),
    )


__all__ = ["evaluate"]
