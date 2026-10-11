"""Typed failures for canonical market-data acquisition."""


class ProviderError(RuntimeError):
    """Base error with a stable public code and retryability classification."""

    code = "PROVIDER_ERROR"
    retryable = False


class ProviderConfigurationError(ProviderError):
    code = "CONFIGURATION_ERROR"


class ProviderAuthenticationError(ProviderError):
    code = "AUTHENTICATION_ERROR"


class UnsupportedProviderRequestError(ProviderError):
    code = "UNSUPPORTED_REQUEST"


class ProviderRateLimitError(ProviderError):
    code = "RATE_LIMIT"
    retryable = True


class ProviderTimeoutError(ProviderError):
    code = "TIMEOUT"
    retryable = True


class ProviderUnavailableError(ProviderError):
    code = "PROVIDER_UNAVAILABLE"
    retryable = True


class IncompleteProviderResponseError(ProviderError):
    code = "INCOMPLETE_RESPONSE"


class InvalidProviderDataError(ProviderError):
    code = "INVALID_PROVIDER_DATA"

    def __init__(
        self,
        message,
        *,
        failure_stage=None,
        validation_rule=None,
        affected_symbol=None,
        affected_date=None,
        affected_field=None,
        safe_actual_value_summary=None,
        safe_expected_constraint=None,
        rejected_record_count=1,
        additional_failure_count=0,
        range_evidence=None,
    ):
        """Carry safe, typed evidence without retaining raw provider payloads."""

        super().__init__(message)
        self.failure_stage = failure_stage
        self.validation_rule = validation_rule
        self.affected_symbol = affected_symbol
        self.affected_date = affected_date
        self.affected_field = affected_field
        self.safe_actual_value_summary = safe_actual_value_summary
        self.safe_expected_constraint = safe_expected_constraint
        self.rejected_record_count = rejected_record_count
        self.additional_failure_count = additional_failure_count
        self.range_evidence = range_evidence


class ProviderNormalizationError(ProviderError):
    code = "NORMALIZATION_FAILURE"


class CorporateActionUnavailableError(ProviderError):
    code = "CORPORATE_ACTION_UNAVAILABLE"
