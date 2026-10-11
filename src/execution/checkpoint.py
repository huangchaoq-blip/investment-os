"""Complete, content-addressed execution recovery state."""

from collections.abc import Mapping
from dataclasses import dataclass
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile

from .context import ExecutionContext, ExecutionMetadata
from .runtime_values import canonical_json, freeze_value, require_text, thaw_value


CHECKPOINT_SCHEMA_VERSION = "execution-checkpoint-v1"
CURRENT_POINTER_SCHEMA_VERSION = "execution-checkpoint-current-v1"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_NO_EXPECTATION = object()


class CheckpointError(RuntimeError):
    """Base error for invalid or unavailable runtime recovery state."""


class CheckpointConflictError(CheckpointError):
    """Raised when the active Checkpoint changed before persistence."""


class CheckpointCorruptError(CheckpointError):
    """Raised when persisted state does not match its stable identity."""


@dataclass(frozen=True)
class Checkpoint:
    checkpoint_id: str
    timeline_id: str
    execution_context: ExecutionContext
    execution_metadata: ExecutionMetadata
    portfolio_state: Mapping
    parent_checkpoint_id: str | None = None
    schema_version: str = CHECKPOINT_SCHEMA_VERSION

    def __post_init__(self):
        if self.schema_version != CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("Unsupported Checkpoint schema_version.")
        _require_safe_id(self.checkpoint_id, "checkpoint_id")
        _require_safe_id(self.timeline_id, "timeline_id")
        if self.parent_checkpoint_id is not None:
            _require_safe_id(self.parent_checkpoint_id, "parent_checkpoint_id")
        if not isinstance(self.execution_context, ExecutionContext):
            raise TypeError("execution_context must be an ExecutionContext.")
        if not isinstance(self.execution_metadata, ExecutionMetadata):
            raise TypeError("execution_metadata must be ExecutionMetadata.")
        state = freeze_value(self.portfolio_state)
        if not isinstance(state, Mapping):
            raise TypeError("portfolio_state must be a mapping.")
        object.__setattr__(self, "portfolio_state", state)
        if self.checkpoint_id != _checkpoint_id(self._identity_payload()):
            raise CheckpointCorruptError(
                "Checkpoint identity does not match its canonical content."
            )

    @classmethod
    def create(
        cls,
        *,
        timeline_id,
        execution_context,
        execution_metadata,
        portfolio_state,
        parent_checkpoint_id=None,
    ):
        payload = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "timeline_id": timeline_id,
            "execution_context": execution_context.to_dict(),
            "execution_metadata": execution_metadata.to_dict(),
            "portfolio_state": thaw_value(freeze_value(portfolio_state)),
            "parent_checkpoint_id": parent_checkpoint_id,
        }
        return cls(
            checkpoint_id=_checkpoint_id(payload),
            timeline_id=timeline_id,
            execution_context=execution_context,
            execution_metadata=execution_metadata,
            portfolio_state=portfolio_state,
            parent_checkpoint_id=parent_checkpoint_id,
        )

    @property
    def timeline_position(self):
        return self.execution_context.timeline_position

    @property
    def event_cursor(self):
        return self.execution_metadata.event_cursor

    @property
    def manifest_references(self):
        return {
            "dataset_version": self.execution_context.dataset_version,
            "cache_manifest_id": self.execution_context.cache_manifest_id,
        }

    def _identity_payload(self):
        return {
            "schema_version": self.schema_version,
            "timeline_id": self.timeline_id,
            "execution_context": self.execution_context.to_dict(),
            "execution_metadata": self.execution_metadata.to_dict(),
            "portfolio_state": thaw_value(self.portfolio_state),
            "parent_checkpoint_id": self.parent_checkpoint_id,
        }

    def to_dict(self):
        return {"checkpoint_id": self.checkpoint_id, **self._identity_payload()}

    @classmethod
    def from_dict(cls, payload):
        if not isinstance(payload, Mapping):
            raise TypeError("Checkpoint payload must be a mapping.")
        fields = {
            "schema_version",
            "checkpoint_id",
            "timeline_id",
            "execution_context",
            "execution_metadata",
            "portfolio_state",
            "parent_checkpoint_id",
        }
        if set(payload) != fields:
            raise ValueError("Invalid Checkpoint fields.")
        return cls(
            schema_version=payload.get("schema_version"),
            checkpoint_id=payload.get("checkpoint_id"),
            timeline_id=payload.get("timeline_id"),
            execution_context=ExecutionContext.from_dict(
                payload.get("execution_context")
            ),
            execution_metadata=ExecutionMetadata.from_dict(
                payload.get("execution_metadata")
            ),
            portfolio_state=payload.get("portfolio_state"),
            parent_checkpoint_id=payload.get("parent_checkpoint_id"),
        )


class CheckpointStore:
    """Atomic current-pointer store over immutable Checkpoint documents."""

    def __init__(self, root):
        self.root = Path(root)
        self.checkpoints_path = self.root / "checkpoints"
        self.current_path = self.root / "current.json"
        self.lock_path = self.root / ".checkpoint.lock"

    def save(self, checkpoint, *, expected_current_id=_NO_EXPECTATION):
        if not isinstance(checkpoint, Checkpoint):
            raise TypeError("checkpoint must be a Checkpoint.")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a+", encoding="utf-8") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    return self._save_locked(checkpoint, expected_current_id)
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except OSError as error:
            raise CheckpointError("Checkpoint persistence is unavailable.") from error

    def _save_locked(self, checkpoint, expected_current_id):
        self.checkpoints_path.mkdir(parents=True, exist_ok=True)
        current_id = self._read_current_id()
        if expected_current_id is not _NO_EXPECTATION and current_id != expected_current_id:
            raise CheckpointConflictError(
                "Active Checkpoint changed before the new Checkpoint was persisted."
            )

        destination = self._checkpoint_path(checkpoint.checkpoint_id)
        if destination.exists():
            existing = self.load(checkpoint.checkpoint_id)
            if existing.to_dict() != checkpoint.to_dict():
                raise CheckpointCorruptError(
                    "Existing Checkpoint content differs for the same identity."
                )
        else:
            _atomic_write_json(destination, checkpoint.to_dict())

        self._before_current_pointer_swap(checkpoint)
        pointer = {
            "schema_version": CURRENT_POINTER_SCHEMA_VERSION,
            "checkpoint_id": checkpoint.checkpoint_id,
        }
        _atomic_write_json(self.current_path, pointer)
        return checkpoint

    def load(self, checkpoint_id):
        path = self._checkpoint_path(checkpoint_id)
        if not path.is_file():
            raise CheckpointError(f"Checkpoint is unavailable: {checkpoint_id}.")
        try:
            return Checkpoint.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except CheckpointCorruptError:
            raise
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise CheckpointCorruptError(
                f"Checkpoint is invalid: {checkpoint_id}."
            ) from error

    def load_current(self):
        checkpoint_id = self._read_current_id()
        return None if checkpoint_id is None else self.load(checkpoint_id)

    def _read_current_id(self):
        if not self.current_path.exists():
            return None
        try:
            payload = json.loads(self.current_path.read_text(encoding="utf-8"))
            if set(payload) != {"schema_version", "checkpoint_id"}:
                raise ValueError("Invalid current-pointer fields.")
            if payload.get("schema_version") != CURRENT_POINTER_SCHEMA_VERSION:
                raise ValueError("Unsupported current-pointer schema.")
            checkpoint_id = payload.get("checkpoint_id")
            _require_safe_id(checkpoint_id, "checkpoint_id")
            return checkpoint_id
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise CheckpointCorruptError("Current Checkpoint pointer is invalid.") from error

    def _checkpoint_path(self, checkpoint_id):
        _require_safe_id(checkpoint_id, "checkpoint_id")
        return self.checkpoints_path / f"{checkpoint_id}.json"

    def _before_current_pointer_swap(self, checkpoint):
        return None


def _checkpoint_id(payload):
    digest = sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return "checkpoint-v1-" + digest


def _require_safe_id(value, field):
    require_text(value, field)
    if not _SAFE_ID.fullmatch(value) or ".." in value:
        raise ValueError(f"{field} contains unsafe characters.")


def _atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
