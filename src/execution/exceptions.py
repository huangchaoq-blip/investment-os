class ExecutionValidationError(ValueError):
    """Base error for invalid frozen-contract input."""


class InvalidExecutionIntentError(ExecutionValidationError):
    """Raised when an ExecutionIntent does not satisfy DEC-006."""


class InvalidExecutionContextError(ExecutionValidationError):
    """Raised when an ExecutionContext does not satisfy DEC-008."""


class InvalidPositionTransitionError(ExecutionValidationError):
    """Raised when ordered ExecutionEvents imply an illegal lifecycle transition."""
