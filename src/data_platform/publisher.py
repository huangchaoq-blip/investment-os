"""Atomic, immutable publication of canonical historical dataset candidates."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile

import pandas as pd

from data.historical_ingestion import (
    BAR_COLUMNS,
    CORPORATE_ACTION_COLUMNS,
    DEFAULT_DATASET_ROOT,
    load_versioned_dataset,
)
from data.manifest import (
    DataClass,
    DatasetManifest,
    assert_historical_market_dataset,
    calculate_dataset_checksum,
    create_dataset_manifest,
)

from .models import (
    CanonicalCorporateAction,
    CanonicalDailyBar,
    ProviderQualificationStatus,
)


PUBLISHER_SCHEMA_VERSION = "dataset-publisher-v1"
LATEST_INDEX_SCHEMA_VERSION = "latest-publication-index-v1"


class PublicationState(str, Enum):
    REQUESTED = "REQUESTED"
    STAGED = "STAGED"
    VALIDATED = "VALIDATED"
    PUBLISHED = "PUBLISHED"
    FETCH_FAILED = "FETCH_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    PUBLICATION_FAILED = "PUBLICATION_FAILED"
    BLOCKED = "BLOCKED"


class PublicationStatus(str, Enum):
    PUBLISHED_NEW = "PUBLISHED_NEW"
    REUSED_EXISTING = "REUSED_EXISTING"
    BLOCKED_VALIDATION = "BLOCKED_VALIDATION"
    BLOCKED_CONCURRENCY = "BLOCKED_CONCURRENCY"
    FAILED_PUBLICATION = "FAILED_PUBLICATION"
    FAILED_STORAGE = "FAILED_STORAGE"


class PublishedDatasetCorruptionError(RuntimeError):
    """Raised when an explicit immutable published version no longer verifies."""


@dataclass(frozen=True)
class DatasetPublicationRequest:
    """Validated canonical content submitted to the publication boundary."""

    request_id: str
    required_symbols: tuple[str, ...]
    bars: tuple[CanonicalDailyBar, ...]
    corporate_actions: tuple[CanonicalCorporateAction, ...]
    provider_id: str
    provider_adapter_version: str
    provider_qualification_status: ProviderQualificationStatus
    adjustment_policy_version: str
    creation_context: str
    previous_dataset_version: str | None = None
    upstream_blocking_reasons: tuple[str, ...] = ()

    def __post_init__(self):
        if not str(self.request_id).strip():
            raise ValueError("request_id must not be empty.")
        symbols = tuple(sorted({str(value).strip() for value in self.required_symbols if str(value).strip()}))
        if not symbols:
            raise ValueError("required_symbols must not be empty.")
        if not self.bars:
            raise ValueError("bars must not be empty.")
        if not str(self.provider_id).strip() or not str(self.provider_adapter_version).strip():
            raise ValueError("Provider identity and adapter version are required.")
        if not str(self.adjustment_policy_version).strip() or not str(self.creation_context).strip():
            raise ValueError("Adjustment policy and creation context are required.")
        object.__setattr__(self, "request_id", str(self.request_id).strip())
        object.__setattr__(self, "required_symbols", symbols)
        object.__setattr__(self, "bars", tuple(self.bars))
        object.__setattr__(self, "corporate_actions", tuple(self.corporate_actions))
        object.__setattr__(self, "provider_id", str(self.provider_id).strip())
        object.__setattr__(self, "provider_adapter_version", str(self.provider_adapter_version).strip())
        object.__setattr__(
            self,
            "provider_qualification_status",
            ProviderQualificationStatus(self.provider_qualification_status),
        )
        object.__setattr__(self, "adjustment_policy_version", str(self.adjustment_policy_version).strip())
        object.__setattr__(self, "creation_context", str(self.creation_context).strip())
        object.__setattr__(
            self,
            "previous_dataset_version",
            None if self.previous_dataset_version is None else str(self.previous_dataset_version).strip(),
        )
        object.__setattr__(
            self,
            "upstream_blocking_reasons",
            tuple(str(value) for value in self.upstream_blocking_reasons),
        )


@dataclass(frozen=True)
class PublicationValidationSummary:
    status: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    bar_count: int
    corporate_action_count: int
    content_checksum: str | None

    def to_dict(self):
        return {
            "status": self.status,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "bar_count": self.bar_count,
            "corporate_action_count": self.corporate_action_count,
            "content_checksum": self.content_checksum,
        }


@dataclass(frozen=True)
class PublicationResult:
    status: PublicationStatus
    state: PublicationState
    dataset_version: str | None
    previous_dataset: str | None
    published: bool
    reused_existing: bool
    blocking_reasons: tuple[str, ...]
    validation_summary: PublicationValidationSummary
    staging_path: str | None
    published_path: str | None


class DatasetPublisher:
    """Single-writer local publisher for complete immutable dataset versions."""

    def __init__(self, storage_root=None):
        root = Path(storage_root) if storage_root is not None else DEFAULT_DATASET_ROOT.parents[1]
        self.storage_root = root
        self.published_root = root / "raw" / "versioned"
        self.staging_root = root / "staging"
        self.publication_root = root / "metadata" / "publication"
        self.latest_index_path = self.publication_root / "latest.json"
        self.lock_path = self.publication_root / "locks" / "canonical-store.lock"

    def publish(self, request):
        if not isinstance(request, DatasetPublicationRequest):
            raise TypeError("request must be a DatasetPublicationRequest.")

        previous_dataset = self.latest_dataset_version()
        if not self._acquire_lock(request.request_id):
            return self._result(
                status=PublicationStatus.BLOCKED_CONCURRENCY,
                state=PublicationState.BLOCKED,
                previous_dataset=previous_dataset,
                reasons=("Another publisher lease is active.",),
            )

        try:
            return self._publish_locked(request, previous_dataset)
        finally:
            self._release_lock()

    def latest_dataset_version(self):
        if not self.latest_index_path.exists():
            return None
        try:
            index = json.loads(self.latest_index_path.read_text(encoding="utf-8"))
            version = str(index["dataset_version"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise PublishedDatasetCorruptionError("Latest publication index is invalid.") from error
        return version

    def read_latest_index(self):
        if not self.latest_index_path.exists():
            return None
        try:
            index = json.loads(self.latest_index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PublishedDatasetCorruptionError("Latest publication index is invalid.") from error
        if index.get("schema_version") != LATEST_INDEX_SCHEMA_VERSION:
            raise PublishedDatasetCorruptionError("Latest publication index schema is invalid.")
        if not index.get("dataset_version"):
            raise PublishedDatasetCorruptionError("Latest publication index lacks dataset_version.")
        return index

    def verify_published(self, dataset_version):
        try:
            dataset = load_versioned_dataset(dataset_version, self.published_root)
        except Exception as error:
            raise PublishedDatasetCorruptionError(
                f"Published dataset is unavailable or corrupt: {dataset_version}."
            ) from error
        return {
            "dataset_version": dataset_version,
            "checksum": dataset["manifest"].checksum,
            "symbols": tuple(dataset["manifest"].symbols),
            "row_count": dataset["manifest"].row_count,
        }

    def _publish_locked(self, request, previous_dataset):
        if request.previous_dataset_version and request.previous_dataset_version != previous_dataset:
            return self._result(
                status=PublicationStatus.BLOCKED_VALIDATION,
                state=PublicationState.BLOCKED,
                previous_dataset=previous_dataset,
                reasons=("previous_dataset_version does not match the latest publication.",),
            )

        bars, actions = _dataframes(request)
        stage_path = self._staging_path(request.request_id)

        try:
            content_checksum = calculate_dataset_checksum(bars, actions)
            manifest = create_dataset_manifest(
                dataframe=bars,
                data_class=DataClass.HISTORICAL_MARKET,
                source=request.provider_id,
                schema_version="raw-daily-v1",
                adjustment_policy_version=request.adjustment_policy_version,
                creation_context=request.creation_context,
                notes="Published through canonical immutable dataset publisher.",
                fetched_at=min(bar.fetched_at for bar in request.bars),
                content_checksum=content_checksum,
            )
            candidate = self._stage_candidate(
                stage_path,
                request,
                bars,
                actions,
                manifest,
                previous_dataset,
            )
        except OSError as error:
            return self._result(
                status=PublicationStatus.FAILED_STORAGE,
                state=PublicationState.PUBLICATION_FAILED,
                previous_dataset=previous_dataset,
                reasons=(f"Staging storage failed: {error.__class__.__name__}.",),
                staging_path=stage_path,
            )
        except Exception as error:
            return self._result(
                status=PublicationStatus.FAILED_PUBLICATION,
                state=PublicationState.PUBLICATION_FAILED,
                previous_dataset=previous_dataset,
                reasons=(f"Staging failed: {error.__class__.__name__}.",),
                staging_path=stage_path,
            )

        validation = _validate_publication_content(request, bars, actions)
        self._write_validation(candidate, validation)
        if validation.status != "PASS":
            return self._result(
                status=PublicationStatus.BLOCKED_VALIDATION,
                state=PublicationState.VALIDATION_FAILED,
                dataset_version=manifest.dataset_version,
                previous_dataset=previous_dataset,
                reasons=validation.blockers,
                validation=validation,
                staging_path=stage_path,
            )

        destination = self.published_root / manifest.dataset_version
        if destination.exists():
            try:
                existing = self.verify_published(manifest.dataset_version)
            except PublishedDatasetCorruptionError as error:
                return self._result(
                    status=PublicationStatus.FAILED_PUBLICATION,
                    state=PublicationState.PUBLICATION_FAILED,
                    dataset_version=manifest.dataset_version,
                    previous_dataset=previous_dataset,
                    reasons=(str(error),),
                    validation=validation,
                    staging_path=stage_path,
                )
            if existing["checksum"] != manifest.checksum:
                return self._result(
                    status=PublicationStatus.FAILED_PUBLICATION,
                    state=PublicationState.PUBLICATION_FAILED,
                    dataset_version=manifest.dataset_version,
                    previous_dataset=previous_dataset,
                    reasons=("Dataset version collision has a different checksum.",),
                    validation=validation,
                    staging_path=stage_path,
                )
            self._remove_stage(stage_path)
            if previous_dataset is None:
                self._write_latest_index(manifest.dataset_version, request.request_id)
            return self._result(
                status=PublicationStatus.REUSED_EXISTING,
                state=PublicationState.PUBLISHED,
                dataset_version=manifest.dataset_version,
                previous_dataset=previous_dataset,
                reused_existing=True,
                validation=validation,
                staging_path=stage_path,
                published_path=destination,
            )

        try:
            self._before_atomic_publish(candidate, manifest)
            self._verify_staged_candidate(candidate, manifest)
            self._mark_candidate_published(candidate)
        except Exception as error:
            return self._result(
                status=PublicationStatus.BLOCKED_VALIDATION,
                state=PublicationState.VALIDATION_FAILED,
                dataset_version=manifest.dataset_version,
                previous_dataset=previous_dataset,
                reasons=(f"Staged candidate verification failed: {error.__class__.__name__}.",),
                validation=validation,
                staging_path=stage_path,
            )

        try:
            self._assert_same_filesystem(candidate, destination)
            self.published_root.mkdir(parents=True, exist_ok=True)
            os.replace(candidate, destination)
            self._write_latest_index(manifest.dataset_version, request.request_id)
            self._remove_stage(stage_path)
        except OSError as error:
            return self._result(
                status=PublicationStatus.FAILED_STORAGE,
                state=PublicationState.PUBLICATION_FAILED,
                dataset_version=manifest.dataset_version,
                previous_dataset=previous_dataset,
                reasons=(f"Atomic publication failed: {error.__class__.__name__}.",),
                validation=validation,
                staging_path=stage_path,
            )
        except Exception as error:
            return self._result(
                status=PublicationStatus.FAILED_PUBLICATION,
                state=PublicationState.PUBLICATION_FAILED,
                dataset_version=manifest.dataset_version,
                previous_dataset=previous_dataset,
                reasons=(f"Atomic publication failed: {error.__class__.__name__}.",),
                validation=validation,
                staging_path=stage_path,
            )

        return self._result(
            status=PublicationStatus.PUBLISHED_NEW,
            state=PublicationState.PUBLISHED,
            dataset_version=manifest.dataset_version,
            previous_dataset=previous_dataset,
            published=True,
            validation=validation,
            staging_path=stage_path,
            published_path=destination,
        )

    def _stage_candidate(
        self,
        stage_path,
        request,
        bars,
        actions,
        manifest,
        previous_dataset,
    ):
        self._remove_stage(stage_path)
        candidate = stage_path / "dataset"
        candidate.mkdir(parents=True, exist_ok=False)
        bars.to_parquet(candidate / "bars.parquet", index=False)
        actions.to_parquet(candidate / "corporate_actions.parquet", index=False)
        (candidate / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
        (candidate / "coverage.json").write_text(
            json.dumps(_coverage_report(bars, request.required_symbols), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        quality = {
            "overall_status": "PENDING",
            "limitations": [],
            "publication_validation": {"status": "PENDING"},
        }
        (candidate / "quality.json").write_text(
            json.dumps(quality, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        publication = {
            "schema_version": PUBLISHER_SCHEMA_VERSION,
            "state": PublicationState.STAGED.value,
            "dataset_version": manifest.dataset_version,
            "previous_dataset_version": previous_dataset,
            "provider_id": request.provider_id,
            "provider_adapter_version": request.provider_adapter_version,
            "provider_qualification_status": request.provider_qualification_status.value,
            "content_checksum": manifest.checksum,
        }
        (candidate / "publication.json").write_text(
            json.dumps(publication, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return candidate

    def _write_validation(self, candidate, validation):
        quality = {
            "overall_status": validation.status,
            "limitations": list(validation.warnings),
            "publication_validation": validation.to_dict(),
        }
        (candidate / "quality.json").write_text(
            json.dumps(quality, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        publication_path = candidate / "publication.json"
        publication = json.loads(publication_path.read_text(encoding="utf-8"))
        publication["state"] = (
            PublicationState.VALIDATED.value
            if validation.status == "PASS"
            else PublicationState.VALIDATION_FAILED.value
        )
        publication_path.write_text(
            json.dumps(publication, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def _mark_candidate_published(self, candidate):
        publication_path = candidate / "publication.json"
        publication = json.loads(publication_path.read_text(encoding="utf-8"))
        publication["state"] = PublicationState.PUBLISHED.value
        publication_path.write_text(
            json.dumps(publication, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def _verify_staged_candidate(self, candidate, manifest):
        bars = pd.read_parquet(candidate / "bars.parquet")
        actions = pd.read_parquet(candidate / "corporate_actions.parquet")
        loaded_manifest = DatasetManifest.from_json(
            (candidate / "manifest.json").read_text(encoding="utf-8")
        )
        checksum = calculate_dataset_checksum(bars, actions)
        assert_historical_market_dataset(loaded_manifest, actual_checksum=checksum)
        if loaded_manifest.dataset_version != manifest.dataset_version:
            raise ValueError("Staged manifest dataset version changed.")

    def _before_atomic_publish(self, candidate, manifest):
        """Test seam for simulating interruption or staged corruption."""

    def _write_latest_index(self, dataset_version, request_id):
        self.publication_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": LATEST_INDEX_SCHEMA_VERSION,
            "dataset_version": dataset_version,
            "request_id": request_id,
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".latest-", dir=self.publication_root
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(temporary, self.latest_index_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _acquire_lock(self, request_id):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return False
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"request_id": request_id}) + "\n")
        return True

    def _release_lock(self):
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass

    def _staging_path(self, request_id):
        digest = sha256(request_id.encode("utf-8")).hexdigest()[:16]
        return self.staging_root / f"request-{digest}"

    def _assert_same_filesystem(self, candidate, destination):
        candidate_device = os.stat(candidate.parent).st_dev
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination_device = os.stat(destination.parent).st_dev
        if candidate_device != destination_device:
            raise OSError("Staging and published roots must share a filesystem.")

    def _write_failed_validation(self, stage_path, validation):
        self._remove_stage(stage_path)
        stage_path.mkdir(parents=True, exist_ok=False)
        (stage_path / "validation.json").write_text(
            json.dumps(validation.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _remove_stage(self, stage_path):
        if stage_path.exists():
            shutil.rmtree(stage_path)

    def _result(
        self,
        status,
        state,
        dataset_version=None,
        previous_dataset=None,
        published=False,
        reused_existing=False,
        reasons=(),
        validation=None,
        staging_path=None,
        published_path=None,
    ):
        return PublicationResult(
            status=status,
            state=state,
            dataset_version=dataset_version,
            previous_dataset=previous_dataset,
            published=published,
            reused_existing=reused_existing,
            blocking_reasons=tuple(reasons),
            validation_summary=validation or PublicationValidationSummary(
                status="NOT_RUN", blockers=(), warnings=(), bar_count=0,
                corporate_action_count=0, content_checksum=None,
            ),
            staging_path=None if staging_path is None else str(staging_path),
            published_path=None if published_path is None else str(published_path),
        )


def _dataframes(request):
    bars = pd.DataFrame([bar.to_record() for bar in request.bars], columns=BAR_COLUMNS)
    actions = pd.DataFrame(
        [action.to_record() for action in request.corporate_actions],
        columns=CORPORATE_ACTION_COLUMNS,
    )
    return (
        bars.sort_values(["code", "date"], kind="stable").reset_index(drop=True),
        actions.sort_values(["code", "event_date", "action_type"], kind="stable").reset_index(drop=True),
    )


def _validate_publication_content(request, bars, actions):
    blockers = list(request.upstream_blocking_reasons)
    warnings = []
    if request.provider_qualification_status not in {
        ProviderQualificationStatus.QUALIFIED_FOR_RESEARCH,
        ProviderQualificationStatus.QUALIFIED_FOR_DAILY_PAPER_OPERATION,
    }:
        blockers.append(
            "Provider is not qualified for canonical historical dataset publication."
        )
    received_symbols = tuple(sorted(str(value) for value in bars["code"].unique()))
    missing_symbols = tuple(sorted(set(request.required_symbols) - set(received_symbols)))
    if missing_symbols:
        blockers.append("Missing required symbols: " + ", ".join(missing_symbols) + ".")
    duplicate_count = int(bars.duplicated(["code", "date"]).sum())
    if duplicate_count:
        blockers.append(f"Duplicate canonical symbol/date keys: {duplicate_count}.")
    if set(bars["source"].astype(str)) != {request.provider_id}:
        blockers.append("Bars do not have one canonical provider identity.")
    if not actions.empty and set(actions["source"].astype(str)) != {request.provider_id}:
        blockers.append("Corporate actions do not have one canonical provider identity.")
    if actions.empty:
        warnings.append("No corporate-action evidence was supplied.")

    checksum = None
    try:
        checksum = calculate_dataset_checksum(bars, actions)
    except Exception as error:
        blockers.append(f"Canonical checksum validation failed: {error.__class__.__name__}.")
    return PublicationValidationSummary(
        status="PASS" if not blockers else "FAIL",
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        bar_count=len(bars),
        corporate_action_count=len(actions),
        content_checksum=checksum,
    )


def _coverage_report(bars, required_symbols):
    codes = {}
    for code, group in bars.groupby("code", sort=True):
        dates = pd.to_datetime(group["date"], errors="raise")
        codes[str(code)] = {
            "row_count": int(len(group)),
            "actual_date_from": dates.min().date().isoformat(),
            "actual_date_to": dates.max().date().isoformat(),
        }
    return {
        "required_symbols": list(required_symbols),
        "codes": codes,
        "gap_interpretation": "Publication does not infer a trading calendar.",
    }
