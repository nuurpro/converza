"""Safe operator-visible failure categories; provider bodies stay server-side."""


class LanguageServiceUnavailable(RuntimeError):
    """The configured provider explicitly reports its language service unavailable."""
