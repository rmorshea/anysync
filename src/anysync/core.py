from __future__ import annotations

import os
from collections.abc import Awaitable, Coroutine, Generator
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar

import anyio
from sniffio import AsyncLibraryNotFoundError, current_async_library

P = ParamSpec("P")
R = TypeVar("R")


def anysync(func: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, AnySync[R]]:
    """Allow an async function to optionally run synchronously by calling `run()` on the result."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> AnySync[R]:
        return AnySync(func(*args, **kwargs))

    return wrapper


class AnySync(Awaitable[R]):
    """Wrapper for a coroutine that can be run synchronously."""

    def __init__(self, coro: Coroutine[Any, Any, R]) -> None:
        self._coro = coro

    def __await__(self) -> Generator[None, None, R]:
        return self._coro.__await__()

    def run(self) -> R:
        """Run the coroutine synchronously."""
        try:
            backend = current_async_library()
        except AsyncLibraryNotFoundError:
            return anyio.run(lambda: self._coro)
        else:
            return _POOL.submit(anyio.run, lambda: self._coro, backend=backend).result()


_POOL = ThreadPoolExecutor(max_workers=os.getenv("ANYIO_MAX_CONCURRENCY"), thread_name_prefix="anysync")
