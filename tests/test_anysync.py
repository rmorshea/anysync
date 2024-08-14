from contextvars import ContextVar
from threading import Thread, current_thread, main_thread
from unittest.mock import patch

from pytest import fixture

from anysync import AnySync, anysync, anysynccontextmanager
from anysync._private import reset_pool

VAR = ContextVar("VAR")


@fixture(autouse=True)
def _init_var():
    token = VAR.set(0)
    yield
    VAR.reset(token)


@anysync
async def wrapped_coro():
    return "value"


@anysynccontextmanager
async def wrapped_ctx():
    yield "value"


async def unwrapped():
    return "value"


async def test_await_wrapped_function():
    assert await wrapped_coro() == "value"


async def test_await_wrapped_coroutine():
    assert await AnySync(unwrapped()) == "value"


def test_sync_wrapped_function():
    assert wrapped_coro().run() == "value"


def test_sync_wrapped_coroutine():
    assert AnySync(unwrapped()).run() == "value"


async def test_sync_wrapped_function_in_async_context():
    assert wrapped_coro().run() == "value"


async def test_sync_wrapped_coroutine_in_async_context():
    assert AnySync(unwrapped()).run() == "value"


async def test_await_wrapped_context_manager():
    async with wrapped_ctx() as value:
        assert value == "value"


def test_sync_wrapped_context_manager():
    with wrapped_ctx() as value:
        assert value == "value"


def test_contextvars_not_shared_between_sync_async_code():
    new = 42

    @anysync
    async def set_var():
        VAR.set(new)
        assert VAR.get() == new

    set_var().run()
    assert VAR.get() == 0


async def test_contextvars_is_shared_within_async_context_manager_but_not_in_sync_code():
    new = 42

    @anysynccontextmanager
    async def set_var():
        VAR.set(new)
        assert VAR.get() == new
        yield
        assert VAR.get() == new

    with set_var():
        assert VAR.get() == 0


async def test_contextvar_changes_not_shared_between_runs():
    """Ensure that we are not modifying the thread pool's context."""

    threads_used = set[Thread]()
    VAR.set(1)

    @anysync
    async def set_var(expected):
        # if we are running in the main thread, we are not testing anything
        thread = current_thread()
        threads_used.add(thread)
        assert thread is not main_thread()

        new = VAR.get() + 1
        VAR.set(new)
        assert VAR.get() == expected

    reset_pool()
    with patch.dict("os.environ", {"ANYSYNC_THREAD_COUNT_MAX": "1"}):
        set_var(expected=2).run()
        set_var(expected=2).run()

    assert VAR.get() == 1
    # we'd only be able to detect an issue if we use the same thread more than once
    assert len(threads_used) == 1
