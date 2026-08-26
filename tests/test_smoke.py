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
