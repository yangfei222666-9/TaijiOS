import numpy as np
import pytest
from coherent_engine.core.cache import LockPointCache


@pytest.fixture
def black_frame():
    return np.zeros((480, 640, 3), dtype=np.uint8)


@pytest.fixture
def white_frame():
    return np.ones((480, 640, 3), dtype=np.uint8) * 255


@pytest.fixture
async def local_cache():
    """LockPointCache that always falls back to local memory."""
    cache = LockPointCache(redis_url="redis://localhost:1")  # unreachable
    yield cache
    await cache.close()
