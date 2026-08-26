"""Smoke test to verify the package is importable and CI has something to run."""


def test_indiquant_importable() -> None:
    """Package root should be importable."""
    import indiquant

    assert indiquant.__name__ == "indiquant"


def test_settings_defaults() -> None:
    """Settings should load with defaults (no .env required)."""
    from indiquant.config.settings import IndiQuantSettings

    s = IndiQuantSettings()
    assert s.log_level == "INFO"


def test_logging_setup() -> None:
    """Ensure logging can be set up without errors."""
    from indiquant.logging import setup_logging

    setup_logging(level="DEBUG")
    # Call it twice to ensure idempotency
    setup_logging()
