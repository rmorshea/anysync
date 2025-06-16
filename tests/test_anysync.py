import gc
from contextvars import ContextVar
from math import factorial
from threading import Event as ThreadEvent
from threading import Thread
from threading import current_thread
from threading import main_thread

import pytest

import anysync

VAR = ContextVar("VAR")


@pytest.fixture(autouse=True)
def _init_var():
    token = VAR.set(0)
    yield
    VAR.reset(token)


async def simple_coro():
    """A simple coroutine that returns a value."""
    return "value"


@anysync.coroutine
async def wrapped_coro():
    return "value"


@anysync.contextmanager
async def wrapped_ctx():
    yield "value"


@anysync.iterator
async def wrapped_iter():
    yield 1
    yield 2
    yield 3


@anysync.generator
async def wrapped_gen():
    value = yield 1
    yield value


# --- Coroutine ------------------------------------------------------------------------


def test_run():
    """Test that the run function works as expected."""
    assert anysync.run(simple_coro()) == "value"
    assert anysync.run(wrapped_coro()) == "value"


async def test_await_wrapped_function():
    assert await wrapped_coro() == "value"


def test_sync_wrapped_function():
    assert wrapped_coro().run() == "value"


async def test_sync_wrapped_function_in_async_context():
    test_sync_wrapped_function()


def test_contextvars_not_shared_between_sync_async_code():
    new = 42

    @anysync.coroutine
    async def set_var():
        VAR.set(new)
        assert VAR.get() == new

    set_var().run()
    assert VAR.get() == 0


async def test_contextvar_changes_not_shared_between_runs():
    """Ensure that we are not modifying the thread pool's context."""
    VAR.set(1)

    @anysync.coroutine
    async def set_var(expected):
        # if we are running in the main thread, we are not testing anything
        thread = current_thread()
        assert thread is not main_thread()

        new = VAR.get() + 1
        VAR.set(new)
        assert VAR.get() == expected

    set_var(expected=2).run()
    set_var(expected=2).run()

    assert VAR.get() == 1


# --- Context Manager ------------------------------------------------------------------


async def test_await_wrapped_context_manager():
    async with wrapped_ctx() as value:
        assert value == "value"


def test_sync_wrapped_context_manager():
    with wrapped_ctx() as value:
        assert value == "value"


async def test_sync_wrapped_context_manager_in_async_context():
    test_sync_wrapped_context_manager()


def test_cannot_resuse_context_manager():
    ctx = wrapped_ctx()
    with ctx as value:
        assert value == "value"

    with pytest.raises(
        RuntimeError, match="Cannot reuse async context manager when executed synchronously"
    ):
        with ctx:
            pass  # nocov


def test_exception_during_enter_is_propagated():
    msg = "broken"

    @anysync.contextmanager
    async def broken_ctx():
        raise ValueError(msg)
        yield

    with pytest.raises(ValueError, match=msg):
        with broken_ctx():
            pass  # nocov


def test_exception_during_exit_is_propagated():
    msg = "broken"

    @anysync.contextmanager
    async def broken_ctx():
        yield
        raise ValueError(msg)

    with pytest.raises(ValueError, match=msg):
        with broken_ctx():
            pass  # nocov


def test_exception_during_yield_is_propagated():
    msg = "broken"

    @anysync.contextmanager
    async def broken_ctx():
        try:
            yield
        except ValueError as exc:
            assert str(exc) == msg  # noqa: PT017
            raise
        else:  # nocov
            raise AssertionError

    with pytest.raises(ValueError, match=msg):
        with broken_ctx():
            raise ValueError(msg)


async def test_contextvars_shared_within_async_context():
    new = 42

    @anysync.contextmanager
    async def set_var():
        VAR.set(new)
        assert VAR.get() == new
        yield
        assert VAR.get() == new

    with set_var():
        assert VAR.get() == 0
    assert VAR.get() == 0


# --- Generator ------------------------------------------------------------------------


async def test_async_for_wrapped_generator():
    assert [value async for value in wrapped_iter()] == [1, 2, 3]


def test_sync_for_wrapped_generator():
    assert list(wrapped_iter()) == [1, 2, 3]


async def test_sync_for_wrapped_generator_in_async_context():
    test_sync_for_wrapped_generator()


async def test_contextvars_shared_within_async_for():
    new = 42

    @anysync.generator
    async def set_var():
        VAR.set(new)
        yield VAR.get()
        yield VAR.get()
        yield VAR.get()

    assert list(set_var()) == [new, new, new]
    assert VAR.get() == 0


async def test_async_for_with_early_break_eventually_stops():
    did_stop = ThreadEvent()

    @anysync.generator
    async def gen():
        try:
            while True:
                yield
        finally:
            did_stop.set()

    next(iter(gen()))
    # only stops after the generator is garbage collected
    gc.collect()

    did_stop.wait(timeout=5)


async def test_async_next_wrapped_generator():
    gen = wrapped_iter()

    values = []
    values.extend(
        (
            await anext(gen),
            await anext(gen),
            await anext(gen),
        )
    )
    assert values == [1, 2, 3]

    with pytest.raises(StopAsyncIteration):
        await anext(gen)


def test_sync_next_wrapped_generator():
    gen = wrapped_iter()

    values = []
    values.extend(
        (
            next(gen),
            next(gen),
            next(gen),
        )
    )
    assert values == [1, 2, 3]

    with pytest.raises(StopIteration):
        next(gen)


async def test_sync_next_wrapped_generator_in_async_context():
    test_sync_next_wrapped_generator()


async def test_contextvars_not_shared_between_async_next_calls():
    new = 42

    @anysync.generator
    async def set_var():
        VAR.set(new)
        yield VAR.get()
        yield VAR.get()
        yield VAR.get()

    gen = set_var()
    assert next(gen) == new
    assert VAR.get() == 0
    assert next(gen) == 0
    assert VAR.get() == 0
    assert next(gen) == 0
    assert VAR.get() == 0


async def test_async_send_wrapped_generator():
    gen = wrapped_gen()

    assert await gen.asend(None) == 1
    msg = 42
    assert await gen.asend(msg) == msg

    with pytest.raises(StopAsyncIteration):
        await gen.asend(None)


def test_sync_send_wrapped_generator():
    gen = wrapped_gen()

    assert gen.send(None) == 1
    msg = 42
    assert gen.send(msg) == msg

    with pytest.raises(StopIteration):
        gen.send(None)


async def test_sync_send_wrapped_generator_in_async_context():
    test_sync_send_wrapped_generator()


# --- Generator throw ------------------------------------------------------------------


async def test_async_throw_wrapped_generator():
    gen = wrapped_gen()

    with pytest.raises(ZeroDivisionError):
        await gen.athrow(ZeroDivisionError)

    with pytest.raises(StopAsyncIteration):
        await anext(gen)


def test_sync_throw_wrapped_generator():
    gen = wrapped_gen()

    with pytest.raises(ZeroDivisionError):
        gen.throw(ZeroDivisionError)

    with pytest.raises(StopIteration):
        next(gen)


async def test_sync_throw_wrapped_generator_in_async_context():
    test_sync_throw_wrapped_generator()


# --- Context Vars ---------------------------------------------------------------------


def test_re_entrant_coroutine_does_not_deadlock():
    threads_used: set[Thread] = set()

    @anysync.coroutine
    async def recursive_func(count):
        threads_used.add(current_thread())
        if new_count := count - 1:
            # call twice to see that we spawn two threads here
            recursive_func(new_count).run()
            recursive_func(new_count).run()

    call_count = 2
    recurse_count = 3

    for _ in range(call_count):
        recursive_func(recurse_count).run()

    assert len(threads_used) == (
        # threads spawned by recursive calls
        factorial(recurse_count) * call_count
        # the main thread's worker is reused so subtract
        - call_count
    )
