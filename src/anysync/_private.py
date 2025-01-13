from __future__ import annotations

from concurrent.futures import Future
from contextlib import contextmanager
from contextlib import suppress
from threading import Thread
from threading import current_thread
from typing import TYPE_CHECKING
from typing import Any
from weakref import WeakSet

from anyio import create_task_group
from anyio import run as anyio_run
from anyio.from_thread import BlockingPortal

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from collections.abc import Callable
    from collections.abc import Iterator

    from anyio.abc import TaskGroup


@contextmanager
def thread_worker_task_portal(func: Callable[[], Awaitable[Any]]) -> Iterator[BlockingPortal]:
    """Run a long running coroutine in a separate thread for the duration of the context."""
    task_group_future: Future[TaskGroup] = Future()

    async def main() -> None:
        async with create_task_group() as task_group:
            task_group_future.set_result(task_group)
            task_group.start_soon(func)

    with thread_worker_portal() as portal:
        main_future = portal.start_task_soon(main)
        task_group = task_group_future.result()
        try:
            yield portal
        finally:
            portal.call(task_group.cancel_scope.cancel)
            main_future.result()


@contextmanager
def thread_worker_portal() -> Iterator[BlockingPortal]:
    """Context manager that yields a blocking portal for running tasks in a separate thread."""
    global _GLOBAL_PORTAL

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
        with suppress(RuntimeError):
            portal.call(portal.stop, cancel_remaining_tasks)
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
