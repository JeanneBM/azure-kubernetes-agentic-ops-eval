"""S01: repository transposition; mocked development checks."""
import pytest

from .support import NEW, assert_correct_recovery, wire


@pytest.mark.parametrize("repetition", range(1, 6))
def test_s01_corrects_only_the_intended_image(repetition):
    assert_correct_recovery(*wire(NEW))
