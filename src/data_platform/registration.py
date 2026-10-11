"""Safe registration of verified legacy-layout immutable datasets."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

from data.corporate_action_normalization import load_canonical_actions
from data.historical_ingestion import DEFAULT_DATASET_ROOT, load_versioned_dataset
from data.manifest import DATASET_VERSION_PATTERN, DataClass

from .models import ProviderQualificationStatus
from .publisher import (
    DatasetPublisher,
    LATEST_INDEX_SCHEMA_VERSION,
    PublicationState,
)


REGISTRATION_SCHEMA_VERSION = "existing-dataset-registration-v1"
REGISTRATION_TOOL_VERSION = "WO-057-existing-dataset-registrar-v1"
REGISTRATION_DIRECTORY = "registrations"


class ExistingDatasetRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    REUSED_EXISTING = "REUSED_EXISTING"
    BLOCKED_CONFLICT = "BLOCKED_CONFLICT"
    BLOCKED_CONCURRENCY = "BLOCKED_CONCURRENCY"
    FAILED_VALIDATION = "FAILED_VALIDATION"
    FAILED_STORAGE = "FAILED_STORAGE"


@dataclass(frozen=True)
class ExistingDatasetRegistrationResult:
    status: ExistingDatasetRegistrationStatus
    dataset_version: str
    registered: bool
    reused_existing: bool
    latest_updated: bool
    blocking_reasons: tuple[str, ...]
    registration_path: str | None
    latest_index_path: str | None
    content_checksum: str | None
    manifest_file_checksum: str | None
    provider_qualification: ProviderQualificationStatus | None


class ExistingDatasetRegistrationError(ValueError):
    """Raised internally when legacy content is ineligible for registration."""


class ExistingDatasetRegistrar:
    """Register verified immutable content without copying or mutating it."""

    def __init__(self, storage_root=None, clock=None, publisher=None):
        root = (
            DEFAULT_DATASET_ROOT.parents[1]
            if storage_root is None
            else Path(storage_root)
        )
        self._publisher = publisher or DatasetPublisher(root)
        self._clock = clock or _utc_now

    @property
    def publisher(self):
        return self._publisher

    def register(self, dataset_version):
        dataset_version = str(dataset_version).strip()
        try:
            evidence = self._validate(dataset_version)
        except Exception:
            return self._result(
                ExistingDatasetRegistrationStatus.FAILED_VALIDATION,
                dataset_version,
                reasons=("Existing dataset could not be registered safely.",),
            )

        request_id = f"existing-dataset-registration:{dataset_version}"
        if not self._acquire_lock(request_id):
            return self._result(
                ExistingDatasetRegistrationStatus.BLOCKED_CONCURRENCY,
                dataset_version,
                evidence=evidence,
                reasons=("Another canonical publication operation is active.",),
            )

        try:
            return self._register_locked(dataset_version, request_id, evidence)
        finally:
            self._release_lock()

    def _validate(self, dataset_version):
        if not DATASET_VERSION_PATTERN.fullmatch(dataset_version):
            raise ExistingDatasetRegistrationError("Dataset version format is invalid.")

        dataset_path = self._publisher.published_root / dataset_version
        _assert_safe_dataset_path(dataset_path, self._publisher.published_root)
        required = (
            "bars.parquet",
            "corporate_actions.parquet",
            "manifest.json",
            "coverage.json",
            "quality.json",
            "canonical_corporate_actions.parquet",
            "corporate_action_manifest.json",
        )
        missing = tuple(name for name in required if not (dataset_path / name).is_file())
        if missing:
            raise ExistingDatasetRegistrationError(
                "Existing dataset is incomplete: " + ", ".join(missing) + "."
            )
        if any((dataset_path / name).is_symlink() for name in required):
            raise ExistingDatasetRegistrationError(
                "Existing dataset registration does not accept symlinked canonical files."
            )

        dataset = load_versioned_dataset(dataset_version, self._publisher.published_root)
        manifest = dataset["manifest"]
        if manifest.dataset_version != dataset_version:
            raise ExistingDatasetRegistrationError(
                "Dataset directory and manifest version do not match."
            )
        if manifest.data_class is not DataClass.HISTORICAL_MARKET:
            raise ExistingDatasetRegistrationError(
                "Only HISTORICAL_MARKET datasets can be registered."
            )
        if manifest.schema_version != "raw-daily-v1":
            raise ExistingDatasetRegistrationError("Dataset schema is unsupported.")
        if dataset["quality"].get("overall_status") != "PASS":
            raise ExistingDatasetRegistrationError("Dataset quality status is not PASS.")
        if dataset["quality"].get("checksum_validation") != "PASS":
            raise ExistingDatasetRegistrationError(
                "Dataset checksum validation evidence is not PASS."
            )
        if dataset["quality"].get("manifest_validation") != "PASS":
            raise ExistingDatasetRegistrationError(
                "Dataset manifest validation evidence is not PASS."
            )

        canonical_actions, action_manifest = load_canonical_actions(dataset_path)
        if canonical_actions is None or action_manifest is None:
            raise ExistingDatasetRegistrationError(
                "Canonical corporate-action evidence is incomplete."
            )
        if action_manifest.get("dataset_version") != dataset_version:
            raise ExistingDatasetRegistrationError(
                "Corporate-action evidence references a different dataset version."
            )
        if action_manifest.get("raw_corporate_action_checksum") != manifest.checksum:
            raise ExistingDatasetRegistrationError(
                "Corporate-action provenance does not match dataset content."
            )

        verified = self._publisher.verify_published(dataset_version)
        if verified["checksum"] != manifest.checksum:
            raise ExistingDatasetRegistrationError(
                "Publisher verification and manifest checksum do not match."
            )

        manifest_path = dataset_path / "manifest.json"
        return {
            "dataset_path": dataset_path,
            "manifest": manifest,
            "content_checksum": manifest.checksum,
            "manifest_file_checksum": "sha256:"
            + sha256(manifest_path.read_bytes()).hexdigest(),
            "dataset_file_fingerprint": _dataset_file_fingerprint(dataset_path),
            "canonical_action_checksum": action_manifest[
                "canonical_corporate_action_checksum"
            ],
        }

    def _register_locked(self, dataset_version, request_id, evidence):
        try:
            latest = self._publisher.read_latest_index()
        except Exception:
            return self._result(
                ExistingDatasetRegistrationStatus.FAILED_STORAGE,
                dataset_version,
                evidence=evidence,
                reasons=("Existing latest publication index is invalid.",),
            )
        if latest is not None and latest["dataset_version"] != dataset_version:
            return self._result(
                ExistingDatasetRegistrationStatus.BLOCKED_CONFLICT,
                dataset_version,
                evidence=evidence,
                reasons=("Latest publication index already references another dataset.",),
            )

        registration_path = registration_path_for(self._publisher, dataset_version)
        registered_at = None
        reused = False
        if registration_path.exists():
            try:
                registration = read_registered_publication(
                    self._publisher,
                    dataset_version,
                )
                _assert_registration_matches(registration, evidence)
                registered_at = registration["migration_timestamp"]
                reused = True
            except Exception:
                return self._result(
                    ExistingDatasetRegistrationStatus.FAILED_VALIDATION,
                    dataset_version,
                    evidence=evidence,
                    reasons=("Existing registration evidence is invalid.",),
                )
        else:
            try:
                registered_at = _timestamp(self._clock())
                registration = _registration_record(
                    dataset_version,
                    evidence,
                    registered_at,
                )
                _atomic_write_json(registration_path, registration)
            except Exception:
                return self._result(
                    ExistingDatasetRegistrationStatus.FAILED_STORAGE,
                    dataset_version,
                    evidence=evidence,
                    reasons=("Registration provenance could not be stored safely.",),
                )

        latest_updated = False
        if latest is None:
            try:
                _atomic_write_json(
                    self._publisher.latest_index_path,
                    {
                        "schema_version": LATEST_INDEX_SCHEMA_VERSION,
                        "dataset_version": dataset_version,
                        "request_id": request_id,
                        "registered_at": registered_at,
                        "registration_reference": str(
                            registration_path.relative_to(
                                self._publisher.publication_root
                            )
                        ),
                    },
                )
                latest_updated = True
            except Exception:
                return self._result(
                    ExistingDatasetRegistrationStatus.FAILED_STORAGE,
                    dataset_version,
                    evidence=evidence,
                    reasons=("Latest publication index could not be stored safely.",),
                    registration_path=registration_path,
                )

        status = (
            ExistingDatasetRegistrationStatus.REUSED_EXISTING
            if reused or not latest_updated
            else ExistingDatasetRegistrationStatus.REGISTERED
        )
        return self._result(
            status,
            dataset_version,
            evidence=evidence,
            registered=status is ExistingDatasetRegistrationStatus.REGISTERED,
            reused=status is ExistingDatasetRegistrationStatus.REUSED_EXISTING,
            latest_updated=latest_updated,
            registration_path=registration_path,
        )

    def _acquire_lock(self, request_id):
        lock_path = self._publisher.lock_path
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                lock_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            return False
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"request_id": request_id}, handle, sort_keys=True)
            handle.write("\n")
        return True

    def _release_lock(self):
        try:
            self._publisher.lock_path.unlink()
        except FileNotFoundError:
            pass

    def _result(
        self,
        status,
        dataset_version,
        evidence=None,
        reasons=(),
        registered=False,
        reused=False,
        latest_updated=False,
        registration_path=None,
    ):
        return ExistingDatasetRegistrationResult(
            status=status,
            dataset_version=dataset_version,
            registered=registered,
            reused_existing=reused,
            latest_updated=latest_updated,
            blocking_reasons=tuple(reasons),
            registration_path=(
                None if registration_path is None else str(registration_path)
            ),
            latest_index_path=(
                str(self._publisher.latest_index_path)
                if self._publisher.latest_index_path.exists()
                else None
            ),
            content_checksum=(
                None if evidence is None else evidence["content_checksum"]
            ),
            manifest_file_checksum=(
                None if evidence is None else evidence["manifest_file_checksum"]
            ),
            provider_qualification=(
                None
                if evidence is None
                else ProviderQualificationStatus.PROVISIONAL
            ),
        )


def registration_path_for(publisher, dataset_version):
    return (
        publisher.publication_root
        / REGISTRATION_DIRECTORY
        / f"{dataset_version}.json"
    )


def read_registered_publication(publisher, dataset_version):
    path = registration_path_for(publisher, dataset_version)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != REGISTRATION_SCHEMA_VERSION:
        raise ExistingDatasetRegistrationError("Registration schema is invalid.")
    if payload.get("dataset_version") != dataset_version:
        raise ExistingDatasetRegistrationError("Registration version is invalid.")
    if payload.get("publication_state") != PublicationState.PUBLISHED.value:
        raise ExistingDatasetRegistrationError("Registration is not PUBLISHED.")
    qualification = ProviderQualificationStatus(
        payload["provider_qualification_status"]
    )
    if qualification is not ProviderQualificationStatus.PROVISIONAL:
        raise ExistingDatasetRegistrationError(
            "Legacy registration must preserve PROVISIONAL provider qualification."
        )

    dataset_path = publisher.published_root / dataset_version
    verified = publisher.verify_published(dataset_version)
    manifest_path = dataset_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    canonical_actions, action_manifest = load_canonical_actions(dataset_path)
    if canonical_actions is None or action_manifest is None:
        raise ExistingDatasetRegistrationError(
            "Registered canonical corporate-action evidence is unavailable."
        )
    expected = {
        "source_dataset_version": dataset_version,
        "content_checksum": verified["checksum"],
        "manifest_file_checksum": "sha256:"
        + sha256(manifest_path.read_bytes()).hexdigest(),
        "dataset_file_fingerprint": _dataset_file_fingerprint(dataset_path),
        "canonical_action_checksum": action_manifest[
            "canonical_corporate_action_checksum"
        ],
        "provider_id": str(manifest["source"]),
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ExistingDatasetRegistrationError(
                f"Registration {key} does not match immutable evidence."
            )
    return payload


def read_publication_evidence(publisher, dataset_version, dataset_path=None):
    """Read embedded publisher metadata or external legacy registration evidence."""

    path = (
        publisher.published_root / dataset_version
        if dataset_path is None
        else Path(dataset_path)
    )
    embedded = path / "publication.json"
    if embedded.is_file():
        payload = json.loads(embedded.read_text(encoding="utf-8"))
        if payload.get("dataset_version") != dataset_version:
            raise ExistingDatasetRegistrationError(
                "Embedded publication version is invalid."
            )
        return payload

    registration = read_registered_publication(publisher, dataset_version)
    return {
        **registration,
        "state": registration["publication_state"],
    }


def _registration_record(dataset_version, evidence, registered_at):
    relative = str(
        evidence["dataset_path"].relative_to(evidence["dataset_path"].parents[2])
    )
    manifest = evidence["manifest"]
    return {
        "schema_version": REGISTRATION_SCHEMA_VERSION,
        "publication_state": PublicationState.PUBLISHED.value,
        "dataset_version": dataset_version,
        "source_dataset_version": dataset_version,
        "original_location": relative,
        "registered_published_reference": relative,
        "manifest_file_checksum": evidence["manifest_file_checksum"],
        "content_checksum": evidence["content_checksum"],
        "dataset_file_fingerprint": evidence["dataset_file_fingerprint"],
        "canonical_action_checksum": evidence["canonical_action_checksum"],
        "provider_id": manifest.source,
        "provider_qualification_status": ProviderQualificationStatus.PROVISIONAL.value,
        "migration_timestamp": registered_at,
        "migration_tool_version": REGISTRATION_TOOL_VERSION,
        "migration_result": "REGISTERED_EXISTING",
    }


def _assert_registration_matches(registration, evidence):
    expected = {
        "content_checksum": evidence["content_checksum"],
        "manifest_file_checksum": evidence["manifest_file_checksum"],
        "dataset_file_fingerprint": evidence["dataset_file_fingerprint"],
        "canonical_action_checksum": evidence["canonical_action_checksum"],
        "provider_qualification_status": ProviderQualificationStatus.PROVISIONAL.value,
    }
    for key, value in expected.items():
        if registration.get(key) != value:
            raise ExistingDatasetRegistrationError(
                f"Registration {key} does not match immutable content."
            )


def _assert_safe_dataset_path(dataset_path, published_root):
    dataset_path = Path(dataset_path)
    if dataset_path.is_symlink():
        raise ExistingDatasetRegistrationError(
            "Dataset registration does not accept a symlinked dataset directory."
        )
    root = Path(published_root).resolve()
    try:
        resolved = dataset_path.resolve(strict=True)
    except OSError as error:
        raise ExistingDatasetRegistrationError("Dataset directory is unavailable.") from error
    if resolved.parent != root:
        raise ExistingDatasetRegistrationError("Dataset path is outside the published root.")


def _dataset_file_fingerprint(dataset_path):
    digest = sha256()
    for path in sorted(item for item in Path(dataset_path).iterdir() if item.is_file()):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}-",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _timestamp(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ExistingDatasetRegistrationError(
            "Registration clock must return a timezone-aware datetime."
        )
    return value.astimezone(timezone.utc).isoformat()


def _utc_now():
    return datetime.now(timezone.utc)
