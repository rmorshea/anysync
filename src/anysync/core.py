from __future__ import annotations

from collections.abc import Awaitable, Coroutine, Generator
from contextlib import AbstractAsyncContextManager, AbstractContextManager, asynccontextmanager
from contextvars import copy_context
from functools import wraps
from types import TracebackType
from typing import Any, Callable, ParamSpec, TypeVar

import anyio
from sniffio import AsyncLibraryNotFoundError, current_async_library

from anysync import _private

P = ParamSpec("P")
R = TypeVar("R")


def anysync(func: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, AnySync[R]]:
    """Allow an async function to optionally run synchronously by calling `run()` on the result."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> AnySync[R]:
        return AnySync(func(*args, **kwargs))

    return wrapper


def anysynccontextmanager(func: Callable[P, AbstractAsyncContextManager[R]]) -> Callable[P, AnySyncContextManager[R]]:
    """Allow an async context manager to optionally run synchronously."""

    ctx = asynccontextmanager(func)

    @wraps(ctx)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> AnySyncContextManager[R]:
        return _AnySyncContextManagerWrapper(ctx(*args, **kwargs))

    return wrapper


class AnySync(Awaitable[R]):
    """Wrapper for a coroutine that can be run synchronously."""

    def __init__(self, coro: Coroutine[Any, Any, R]) -> None:
        self._coro = coro

    def __await__(self) -> Generator[None, None, R]:
        return self._coro.__await__()

    def run(self) -> R:
        """Run the coroutine synchronously."""
        ctx = copy_context()
        try:
            backend = current_async_library()
        except AsyncLibraryNotFoundError:
            return anyio.run(ctx.run, lambda: self._coro)
        else:
            return _private.get_pool().submit(ctx.run, anyio.run, lambda: self._coro, backend=backend).result()


class AnySyncContextManager(AbstractContextManager[R], AbstractAsyncContextManager[R]):
    def __enter__(self) -> R:
        return AnySync(self.__aenter__()).run()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None | bool:
        return AnySync(self.__aexit__(exc_type, exc_value, traceback)).run()


class _AnySyncContextManagerWrapper(AnySyncContextManager[R]):
    def __init__(self, manager: AbstractAsyncContextManager[R]) -> None:
        self._manager = manager

    async def __aenter__(self) -> R:
        return await self._manager.__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None | bool:
        return await self._manager.__aexit__(exc_type, exc_value, traceback)
