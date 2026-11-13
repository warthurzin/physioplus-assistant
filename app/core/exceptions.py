class AssistantError(Exception):
    pass


class KnowledgeBaseError(AssistantError):
    pass


class IndexNotLoadedError(AssistantError):
    pass


class IndexMismatchError(AssistantError):
    pass


class LLMError(AssistantError):
    pass


class LLMConfigError(LLMError):
    pass


class LLMUnavailableError(LLMError):
    pass


class LLMRequestError(LLMError):
    pass


class LLMEmptyResponseError(LLMError):
    pass


class ActionsDisabledError(AssistantError):
    pass


class UpstreamError(AssistantError):
    pass


class UpstreamAuthError(UpstreamError):
    pass


class UpstreamNotFoundError(UpstreamError):
    pass


class UpstreamConflictError(UpstreamError):
    pass


class UpstreamValidationError(UpstreamError):
    pass


class UpstreamUnavailableError(UpstreamError):
    pass