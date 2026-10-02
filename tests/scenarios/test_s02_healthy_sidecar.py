"""S02: one failing container and one healthy sidecar; mocked checks."""
import pytest

from .support import NEW, assert_correct_recovery, wire


@pytest.mark.parametrize("repetition", range(1, 6))
@pytest.mark.parametrize("sidecar_first", [False, True], ids=["api-first", "sidecar-first"])
def test_s02_preserves_sidecar_and_unrelated_fields(repetition, sidecar_first):
    assert_correct_recovery(*wire(NEW, sidecar_first=sidecar_first))
