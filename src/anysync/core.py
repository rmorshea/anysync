from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Coroutine, Generator, Iterator
from concurrent.futures import Future
from contextlib import AbstractAsyncContextManager, AbstractContextManager, asynccontextmanager
from functools import wraps
from types import TracebackType
from typing import Any, Callable, ParamSpec, TypeVar, overload

from anyio import create_memory_object_stream
from anyio import run as anyio_run
from sniffio import AsyncLibraryNotFoundError, current_async_library

from anysync._private import identity, thread_worker_portal

P = ParamSpec("P")
R = TypeVar("R")
S = TypeVar("S")
Y = TypeVar("Y")

_ExcInfo = tuple[type[BaseException] | None, BaseException | None, TracebackType | None]


def coroutine(func: Callable[P, Coroutine[None, None, R]]) -> Callable[P, AnySyncCoroutine[R]]:
    """Allow an async function to optionally run synchronously by calling `run()` on the result."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> AnySyncCoroutine[R]:
        return _AnySyncResultWrapper(func(*args, **kwargs))

    return wrapper


@overload
def generator(func: Callable[P, AsyncGenerator[Y, S]]) -> Callable[P, AnySyncGenerator[Y, S]]: ...


@overload
def generator(func: Callable[P, AsyncIterator[Y]]) -> Callable[P, AnySyncIterator[Y]]: ...


def generator(
    func: Callable[P, AsyncGenerator[Y, S]] | Callable[P, AsyncIterator[Y]],
) -> Callable[P, AnySyncGenerator[Y, S] | AnySyncIterator[Y]]:
    """Allow an async generator to optionally run synchronously."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> AnySyncGenerator[Y, S] | AnySyncIterator[Y]:
        return (
            _AnySyncGeneratorWrapper(gen)
            if isinstance(gen := func(*args, **kwargs), AsyncGenerator)
            else _AnySyncIteratorWrapper(gen)
        )

    return wrapper


def contextmanager(func: Callable[P, AsyncIterator[R]]) -> Callable[P, AnySyncContextManager[R]]:
    """Allow an async context manager to optionally run synchronously."""

    ctx = asynccontextmanager(func)

    @wraps(ctx)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> AnySyncContextManager[R]:
        return _AnySyncContextManagerWrapper(ctx(*args, **kwargs))

    return wrapper


class AnySyncCoroutine(Awaitable[R], ABC):
    """Abstract base class for an async function that can be used synchronously."""

    @abstractmethod
    def __await__(self) -> Generator[None, None, R]:
        raise NotImplementedError()  # nocov

    def run(self, timeout: float | None = None) -> R:
        """Run the coroutine synchronously."""
        try:
            current_async_library()
        except AsyncLibraryNotFoundError:
            return anyio_run(identity, self)
        else:
            with thread_worker_portal() as portal:
                return portal.start_task_soon(identity, self).result(timeout)


class AnySyncIterator(AsyncIterator[Y], Iterator[Y], ABC):
    """Abstract base class for an async generator that can be used synchronously."""

    @abstractmethod
    def __aiter__(self) -> AsyncIterator[Y]:
        raise NotImplementedError()  # nocov

    @abstractmethod
    async def __anext__(self) -> Y:
        raise NotImplementedError()  # nocov

    def __iter__(self) -> Iterator[Y]:
        self._setup_portal()
        try:
            while True:
                yield self._blocking_portal.call(self.__anext__)
        except StopAsyncIteration:
            pass

    def __next__(self) -> Y:
        self._setup_portal()
        try:
            return self._blocking_portal.call(self.__anext__)
        except StopAsyncIteration:
            raise StopIteration() from None

    def _setup_portal(self) -> None:
        if hasattr(self, "_blocking_portal_manager"):
            return
        self._blocking_portal_manager = thread_worker_portal()
        self._blocking_portal = self._blocking_portal_manager.__enter__()

    def __del__(self) -> None:
        if hasattr(self, "_blocking_portal_manager"):
            self._blocking_portal_manager.__exit__(None, None, None)


class AnySyncGenerator(AnySyncIterator[Y], AsyncGenerator[Y, S], Generator[Y, S], ABC):
    """Abstract base class for an async generator that can be used synchronously."""

    @abstractmethod
    async def asend(self, value: S) -> Y:
        raise NotImplementedError()  # nocov

    @abstractmethod
    async def athrow(  # type: ignore[reportIncompatibleMethodOverride]
        self,
        typ: type[BaseException],
        val: BaseException | Any = None,
        tb: TracebackType | None = None,
        /,
    ) -> Y:
        raise NotImplementedError()  # nocov

    def send(self, value: S) -> Y:
        self._setup_portal()
        try:
            return self._blocking_portal.call(self.asend, value)
        except StopAsyncIteration:
            raise StopIteration() from None

    def throw(  # type: ignore[reportIncompatibleMethodOverride]
        self,
        typ: type[BaseException],
        val: BaseException | Any = None,
        tb: TracebackType | None = None,
        /,
    ) -> Y:
        self._setup_portal()
        return self._blocking_portal.call(self.athrow, typ, val, tb)


class AnySyncContextManager(AbstractContextManager[R], AbstractAsyncContextManager[R]):
    """Abstract base class for an async context manager that can be used synchronously."""

    _dirty = False

    def __enter__(self) -> R:
        if self._dirty:
            msg = "Cannot reuse async context manager when executed synchronously"
            raise RuntimeError(msg)

        self._dirty = True
        self._enter_future: Future[R] = Future()
        self._exit_future: Future[None | bool] = Future()
        self._send_exc_info, self._recv_exc_info = create_memory_object_stream[_ExcInfo]()
        self._portal_manager = thread_worker_portal()
        self._portal = self._portal_manager.__enter__()

        async def _context() -> None:
            try:
                self._enter_future.set_result(await self.__aenter__())
            except BaseException as exc:
                self._enter_future.set_exception(exc)

            exc_info = await self._recv_exc_info.receive()

            try:
                self._exit_future.set_result(await self.__aexit__(*exc_info))
            except BaseException as exc:
                self._exit_future.set_exception(exc)

        # Start the context manager in the worker thread ensuring that is uses
        # the same contextvars.Context between __aenter__ and __aexit__ calls
        self._portal.start_task_soon(_context)

        return self._enter_future.result()

    def __exit__(
        self,
        typ: type[BaseException] | None = None,
        val: BaseException | None = None,
        tb: TracebackType | None = None,
        /,
    ) -> None | bool:
        self._portal.call(self._send_exc_info.send, (typ, val, tb))
        return self._exit_future.result()


class _AnySyncResultWrapper(AnySyncCoroutine[R]):

    def __init__(self, coroutine: Coroutine[None, None, R]) -> None:
        self._coroutine = coroutine

    def __await__(self) -> Generator[None, None, R]:
        return self._coroutine.__await__()


class _AnySyncIteratorWrapper(AnySyncIterator[Y]):
    def __init__(self, iterator: AsyncIterator[Y]) -> None:
        self._iterator = iterator

    def __aiter__(self) -> AsyncIterator[Y]:
        return self._iterator

    async def __anext__(self) -> Y:
        return await self._iterator.__anext__()


class _AnySyncGeneratorWrapper(_AnySyncIteratorWrapper, AnySyncGenerator[Y, S]):
    def __init__(self, generator: AsyncGenerator[Y, S]) -> None:
        super().__init__(generator)
        self._generator = generator

    async def asend(self, value: S) -> Y:
        return await self._generator.asend(value)

    async def athrow(
        self,
        typ: type[BaseException],
        val: BaseException | Any = None,
        tb: TracebackType | None = None,
        /,
    ) -> Y:
        return await self._generator.athrow(typ, val, tb)


class _AnySyncContextManagerWrapper(AnySyncContextManager[R]):
    def __init__(self, manager: AbstractAsyncContextManager[R]) -> None:
        self._manager = manager

    async def __aenter__(self) -> R:
        return await self._manager.__aenter__()

    async def __aexit__(
        self,
        typ: type[BaseException] | None = None,
        val: BaseException | None = None,
        tb: TracebackType | None = None,
        /,
    ) -> None | bool:
        return await self._manager.__aexit__(typ, val, tb)
