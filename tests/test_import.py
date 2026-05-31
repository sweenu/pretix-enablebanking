from __future__ import annotations

import pretix_enablebanking


def test_version_is_exposed() -> None:
    assert pretix_enablebanking.__version__ == "1.0.4"
