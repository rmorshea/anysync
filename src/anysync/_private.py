from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from threading import Thread, current_thread
from typing import Callable, TypeVar
from weakref import WeakSet

from anyio import run as anyio_run
from anyio.from_thread import BlockingPortal

R = TypeVar("R")
F = TypeVar("F", bound=Callable)


def identity(x: R, /) -> R:
    """Return the argument."""
    return x


@contextmanager
def thread_worker_portal() -> Iterator[BlockingPortal]:
    """Context manager that yields a blocking portal for running tasks in a separate thread.

    This context manager can be used to run blocking tasks in a separate thread. A global portal
    is created on the first call to this function and reused for subsequent calls unless this
    function is called from the same thread the global portal is running on. In that case, a new
    temporary portal is created for the duration of the context manager. The temporary portal is
    necessary to avoid a deadlock.
    """
    global _GLOBAL_PORTAL  # noqa: PLW0603

    if not _GLOBAL_PORTAL:
        # if no global worker exists, create one
        _GLOBAL_PORTAL = _start_worker_portal()[1]
        yield _GLOBAL_PORTAL
        return

    if current_thread() not in _WORKER_THREADS:
        # if the global worker is running on a different thread and is still alive, use it
        yield _GLOBAL_PORTAL
        return

    # otherwise, create a new, temporary worker thread
    with _temporary_portal() as portal:
        yield portal


@contextmanager
def _temporary_portal() -> Iterator[BlockingPortal]:
    thread, portal = _start_worker_portal()

    # a small snippet mimicking part of anyio's start_blocking_portal
    # https://github.com/agronholm/anyio/blob/c1aff53d8ae5ddc2cf1b8558614a7a2d60c12518/src/anyio/from_thread.py#L451-L501
    cancel_remaining_tasks = False
    try:
        yield portal
    except BaseException:  # nocov
        cancel_remaining_tasks = True
        raise
    finally:
        try:
            portal.call(portal.stop, cancel_remaining_tasks)
        except RuntimeError:  # nocov
            pass
        thread.join()


def _start_worker_portal() -> tuple[Thread, BlockingPortal]:
    portal_future: Future[BlockingPortal] = Future()
    thread = Thread(target=anyio_run, args=(_worker_task, portal_future), daemon=True)
    thread.start()
    portal = portal_future.result()
    _WORKER_THREADS.add(thread)
    return thread, portal


async def _worker_task(future: Future[BlockingPortal]) -> None:
    async with BlockingPortal() as portal:
        future.set_result(portal)
        await portal.sleep_until_stopped()


_GLOBAL_PORTAL: BlockingPortal | None = None
_WORKER_THREADS: WeakSet[Thread] = WeakSet()
