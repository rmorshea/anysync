import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

T = TypeVar("T")


def get_pool() -> ThreadPoolExecutor:
    global _CURRENT_POOL  # noqa: PLW0603
    try:
        return _CURRENT_POOL
    except NameError:
        _CURRENT_POOL = ThreadPoolExecutor(max_workers=ANYSYNC_THREAD_COUNT_MAX(), thread_name_prefix="anysync")
        return _CURRENT_POOL


def reset_pool() -> None:
    global _CURRENT_POOL  # noqa: PLW0603
    try:
        _CURRENT_POOL.shutdown()
        del _CURRENT_POOL
    except NameError:  # nocov
        pass


def _opt(name: str, cast: Callable[[str | None], T], default: T) -> Callable[[], T]:
    return lambda: default if (v := os.getenv(name)) is None else cast(v)


ANYSYNC_THREAD_COUNT_MAX = _opt("ANYSYNC_THREAD_COUNT_MAX", lambda s: None if s.lower() == "none" else int(s), None)
