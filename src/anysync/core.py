from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from collections.abc import AsyncGenerator
from collections.abc import AsyncIterator
from collections.abc import Callable
from collections.abc import Coroutine
from collections.abc import Generator
from collections.abc import Iterator
from concurrent.futures import Future
from contextlib import AbstractAsyncContextManager
from contextlib import AbstractContextManager
from contextlib import asynccontextmanager
from contextlib import suppress
from functools import wraps
from types import TracebackType
from typing import TYPE_CHECKING
from typing import Any
from typing import Generic
from typing import ParamSpec
from typing import cast

from anyio import BrokenResourceError
from anyio import create_memory_object_stream
from anyio import run as anyio_run
from sniffio import AsyncLibraryNotFoundError
from sniffio import current_async_library
from typing_extensions import TypeVar

from anysync._private import thread_worker_portal
from anysync._private import thread_worker_task_portal

P = ParamSpec("P")
R = TypeVar("R")
S = TypeVar("S")
S_any = TypeVar("S_any", default=Any)
Y = TypeVar("Y")
Y_any = TypeVar("Y_any", default=Any)


_ExcInfo = tuple[type[BaseException] | None, BaseException | None, TracebackType | None]


def run(coro: Coroutine[Any, Any, R]) -> R:
    """Run a coroutine synchronously."""
    return wrap_coroutine(coro).run()


def coroutine(func: Callable[P, Coroutine[Y, S, R]]) -> Callable[P, AnySyncCoroutine[R, Y, S]]:
    """Allow an async function to optionally run synchronously by calling `run()` on the result."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> AnySyncCoroutine[R, Y, S]:
        return wrap_coroutine(func(*args, **kwargs))

    return wrapper


def iterator(func: Callable[P, AsyncIterator[Y]]) -> Callable[P, AnySyncIterator[Y]]:
    """Allow an async iterator to optionally run synchronously."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> AnySyncIterator[Y]:
        return wrap_async_iterator(func(*args, **kwargs))

    return wrapper


def generator(func: Callable[P, AsyncGenerator[Y, S]]) -> Callable[P, AnySyncGenerator[Y, S]]:
    """Allow an async generator to optionally run synchronously."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> AnySyncGenerator[Y, S]:
        return wrap_async_generator(func(*args, **kwargs))

    return wrapper


def contextmanager(func: Callable[P, AsyncIterator[R]]) -> Callable[P, AnySyncContextManager[R]]:
    """Allow an async context manager to optionally run synchronously."""
    ctx = asynccontextmanager(func)

    @wraps(ctx)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> AnySyncContextManager[R]:
        return wrap_async_context_manager(ctx(*args, **kwargs))

    return wrapper


def wrap_coroutine(coroutine: Coroutine[Y, S, R]) -> AnySyncCoroutine[R, Y, S]:
    """Wrap an coroutine so that it can be run synchronously."""
    return coroutine if isinstance(coroutine, AnySyncCoroutine) else AnySyncCoroutine(coroutine)


def wrap_async_iterator(iterator: AsyncIterator[Y]) -> AnySyncIterator[Y]:
    """Wrap an async iterator so that it can be run synchronously."""
    return iterator if isinstance(iterator, AnySyncIterator) else _AnySyncIteratorWrapper(iterator)


def wrap_async_generator(generator: AsyncGenerator[Y, S]) -> AnySyncGenerator[Y, S]:
    """Wrap an async generator so that it can be run synchronously."""
    return (
        generator
        if isinstance(generator, AnySyncGenerator)
        else _AnySyncGeneratorWrapper(generator)
    )


def wrap_async_context_manager(manager: AbstractAsyncContextManager[R]) -> AnySyncContextManager[R]:
    """Wrap an async context manager so that it can be run synchronously."""
    return (
        manager
        if isinstance(manager, AnySyncContextManager)
        else _AnySyncContextManagerWrapper(manager)
    )


def _raise_not_implemented(*a: Any, **kw: Any) -> Any:
    raise NotImplementedError  # nocov


class AnySyncCoroutine(Coroutine[Y_any, S_any, R], Generic[R, Y_any, S_any], ABC):
    """Abstract base class for an async function that can be used synchronously."""

    def __init__(self, coro: Coroutine[Y_any, S_any, R]) -> None:
        """Initialize the coroutine wrapper."""
        self.coro = coro
        self.send = coro.send
        self.throw = coro.throw
        self.close = coro.close

    def __await__(self) -> Generator[Any, Any, R]:
        return self.coro.__await__()

    def run(self, timeout: float | None = None) -> R:
        """Run the coroutine synchronously."""
        try:
            current_async_library()
        except AsyncLibraryNotFoundError:
            return anyio_run(_identity, self)
        else:
            with thread_worker_portal() as portal:
                return portal.start_task_soon(_identity, self).result(timeout)

    if TYPE_CHECKING:  # avoid typing the overloads
        send = Coroutine[Y_any, S_any, R].send
        throw = Coroutine[Y_any, S_any, R].throw
        close = Coroutine[Y_any, S_any, R].close
    else:
        send = _raise_not_implemented
        throw = _raise_not_implemented
        close = _raise_not_implemented


class AnySyncIterator(AsyncIterator[Y], Iterator[Y], ABC):
    """Abstract base class for an async generator that can be used synchronously."""

    @abstractmethod
    def __aiter__(self) -> AsyncIterator[Y]:
        raise NotImplementedError  # nocov

    @abstractmethod
    async def __anext__(self) -> Y:
        raise NotImplementedError  # nocov

    def __iter__(self) -> Iterator[Y]:
        done = cast("Any", object())
        send_stream, recv_stream = create_memory_object_stream[Y](max_buffer_size=1)

        async def sender() -> None:
            with (
                send_stream,
                # BrokenResourceError is raised when recv_stream exits before send_stream.
                # This might happen in the case of an early break while iterating through
                # the generator.
                suppress(BrokenResourceError),
            ):
                async for value in self:
                    await send_stream.send(value)
                await send_stream.send(done)

        with thread_worker_task_portal(sender) as portal:
            with recv_stream:
                while True:
                    result = portal.call(recv_stream.receive)
                    if result is done:
                        break
                    yield result

    def __next__(self) -> Y:
        with thread_worker_portal() as portal:
            try:
                return portal.call(self.__anext__)
            except StopAsyncIteration:
                raise StopIteration from None


class AnySyncGenerator(AnySyncIterator[Y], AsyncGenerator[Y, S], Generator[Y, S], ABC):
    """Abstract base class for an async generator that can be used synchronously."""

    @abstractmethod
    async def asend(self, value: S) -> Y:
        """Send a value into the generator."""
        raise NotImplementedError  # nocov

    @abstractmethod
    async def athrow(  # type: ignore[reportIncompatibleMethodOverride]
        self,
        typ: type[BaseException],
        val: BaseException | Any = None,
        tb: TracebackType | None = None,
        /,
    ) -> Y:
        """Raise an exception in the generator."""
        raise NotImplementedError  # nocov

    def send(self, value: S) -> Y:
        """Send a value into the generator."""
        with thread_worker_portal() as portal:
            try:
                return portal.call(self.asend, value)
            except StopAsyncIteration:
                raise StopIteration from None

    def throw(  # type: ignore[reportIncompatibleMethodOverride]
        self,
        typ: type[BaseException],
        val: BaseException | Any = None,
        tb: TracebackType | None = None,
        /,
    ) -> Y:
        """Raise an exception in the generator."""
        with thread_worker_portal() as portal:
            return portal.call(self.athrow, typ, val, tb)


class AnySyncContextManager(AbstractContextManager[R], AbstractAsyncContextManager[R]):
    """Abstract base class for an async context manager that can be used synchronously."""

    _dirty = False

    def __enter__(self) -> R:
        if self._dirty:
            msg = "Cannot reuse async context manager when executed synchronously"
            raise RuntimeError(msg)

        self._dirty = True
        self._enter_future: Future[R] = Future()
        self._exit_future: Future[bool | None] = Future()
        self._send_exc_info, self._recv_exc_info = create_memory_object_stream[_ExcInfo]()
        self._portal_manager = thread_worker_portal()
        self._portal = self._portal_manager.__enter__()

        async def _context() -> None:
            try:
                self._enter_future.set_result(await self.__aenter__())
            except BaseException as exc:  # noqa: BLE001
                self._enter_future.set_exception(exc)

            exc_info = await self._recv_exc_info.receive()

            try:
                self._exit_future.set_result(await self.__aexit__(*exc_info))
            except BaseException as exc:  # noqa: BLE001
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
    ) -> bool | None:
        self._portal.call(self._send_exc_info.send, (typ, val, tb))
        return self._exit_future.result()


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
        _: TracebackType | None = None,
        /,
    ) -> Y:
        return await self._generator.athrow(val or typ)


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
    ) -> bool | None:
        return await self._manager.__aexit__(typ, val, tb)


def _identity(x: R, /) -> R:
    """Return the argument."""
    return x
