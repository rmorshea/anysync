from contextvars import ContextVar
from threading import Thread, current_thread, main_thread

import pytest
from pytest import fixture

import anysync

VAR = ContextVar("VAR")


@fixture(autouse=True)
def _init_var():
    token = VAR.set(0)
    yield
    VAR.reset(token)


@anysync.coroutine
async def wrapped_coro():
    return "value"


@anysync.contextmanager
async def wrapped_ctx():
    yield "value"


@anysync.generator
async def wrapped_iter():
    yield 1
    yield 2
    yield 3


@anysync.generator
async def wrapped_gen():
    value = yield 1
    yield value


# --- Coroutine ------------------------------------------------------------------------


async def test_await_wrapped_function():
    assert await wrapped_coro() == "value"


def test_sync_wrapped_function():
    assert wrapped_coro().run() == "value"


async def test_sync_wrapped_function_in_async_context():
    test_sync_wrapped_function()


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

    with pytest.raises(RuntimeError, match="Cannot reuse async context manager when executed synchronously"):
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
            assert str(exc) == msg
            raise
        else:
            raise AssertionError()

    with pytest.raises(ValueError, match=msg):
        with broken_ctx():
            raise ValueError(msg)


# --- Generator for --------------------------------------------------------------------


async def test_async_for_wrapped_generator():
    assert [value async for value in wrapped_iter()] == [1, 2, 3]


def test_sync_for_wrapped_generator():
    assert list(wrapped_iter()) == [1, 2, 3]


async def test_sync_for_wrapped_generator_in_async_context():
    test_sync_for_wrapped_generator()


# --- Generator next -------------------------------------------------------------------


async def test_async_next_wrapped_generator():
    gen = wrapped_iter()

    values = []
    values.append(await anext(gen))
    values.append(await anext(gen))
    values.append(await anext(gen))
    assert values == [1, 2, 3]

    with pytest.raises(StopAsyncIteration):
        await anext(gen)


def test_sync_next_wrapped_generator():
    gen = wrapped_iter()

    values = []
    values.append(next(gen))
    values.append(next(gen))
    values.append(next(gen))
    assert values == [1, 2, 3]

    with pytest.raises(StopIteration):
        next(gen)


async def test_sync_next_wrapped_generator_in_async_context():
    test_sync_next_wrapped_generator()


# --- Generator send -------------------------------------------------------------------


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


def test_contextvars_not_shared_between_sync_async_code():
    new = 42

    @anysync.coroutine
    async def set_var():
        VAR.set(new)
        assert VAR.get() == new

    set_var().run()
    assert VAR.get() == 0


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


def test_re_entrant_coroutine_does_not_deadlock():

    threads_used: set[Thread] = set()

    @anysync.coroutine
    async def re_entrant_func(count):
        threads_used.add(current_thread())
        if new_count := count - 1:
            return re_entrant_func(new_count).run()

    count = 10
    re_entrant_func(count).run()

    assert len(threads_used) == count
