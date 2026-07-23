"""Application-layer errors translated to HTTP responses by the API layer."""


class ResourceNotFoundError(LookupError):
    pass


class ApplicationConflictError(RuntimeError):
    pass


class ApplicationValidationError(ValueError):
    pass


class ApplicationUnavailableError(RuntimeError):
    pass
