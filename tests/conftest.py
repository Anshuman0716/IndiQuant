import pytest

from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse


@pytest.fixture
def tmp_lakehouse(tmp_path) -> Lakehouse:
    settings = IndiQuantSettings(data_dir=tmp_path)
    return Lakehouse(settings)
