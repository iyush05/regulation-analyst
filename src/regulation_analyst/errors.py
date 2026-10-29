class ResearchError(ValueError):
    """An expected, safe-to-display failure to establish an answer."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
