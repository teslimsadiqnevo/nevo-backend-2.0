"""One size limit for a lesson, on every door into the pipeline.

/api/content/upload - the one the teacher console posts to - had no size limit
at all and read whatever arrived straight into memory, while the staged route
capped the same kind of file at 50 MB. Two doors to the same pipeline
disagreeing about what fits through.
"""

from __future__ import annotations

import inspect

from nevo.api.frontend_unblockers import MAX_LESSON_UPLOAD_BYTES, upload_content
from nevo.api.product_learning import MAX_UPLOAD_BYTES, _ingest_one_file


def test_the_limit_is_fifty_megabytes() -> None:
    assert MAX_LESSON_UPLOAD_BYTES == 50 * 1024 * 1024


def test_both_routes_use_the_same_number() -> None:
    # Not two constants that agree today: one constant.
    assert MAX_UPLOAD_BYTES is MAX_LESSON_UPLOAD_BYTES


def test_the_console_upload_checks_the_size_before_parsing() -> None:
    source = inspect.getsource(upload_content)

    assert "MAX_LESSON_UPLOAD_BYTES" in source
    assert "413" in source or "REQUEST_ENTITY_TOO_LARGE" in source
    # The check has to sit between reading the file and doing work with it.
    assert source.index("MAX_LESSON_UPLOAD_BYTES") < source.index("_extract_text")


def test_the_staged_upload_still_checks_it_too() -> None:
    assert "MAX_UPLOAD_BYTES" in inspect.getsource(_ingest_one_file)
