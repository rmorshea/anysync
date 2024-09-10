# AnySync

A lightweight library for allowing async functions to be called in a synchronous manner.

```python
import asyncio
from anysync import anysync


@anysync
async def f():
    return 42


assert f().run() == 42


async def main():
    assert await f() == 42


asyncio.run(main())
```

Just `pip install anysync` and you're good to go!

# Usage

## Coroutines

The primary use case for `anysync` is to allow async functions to be called in a
synchronous manner. All you need to do is add the `anysync.coroutine` decorator to your
async function:

```python
import asyncio
import anysync


@anysync.coroutine
async def f():
    return 42


assert f().run() == 42
```

## Generators

You can also use `anysync` with async generators:

```python
import asyncio
import anysync


@anysync.generator
async def gen():
    yield 42


assert list(gen()) == [42]
```

Note that in this case you don't need to call `run()`. The generator will automatically
detect how it's being used and run the coroutine accordingly.

## Context Managers

You can even use AnySync on your async context managers.

```python
import asyncio
import anysync


@@anysync.contextmanager
async def cm():
    yield 42


def test_sync():
    with cm() as x:
        assert x == 42


async def test_async():
    async with cm() as x:
        assert x == 42


test_sync()
asyncio.run(test_async())
```

You can alternatively subclass the `AnySyncContextManager` class:

```python
from anysync import AnySyncContextManager


class CM(AnySyncContextManager):
    async def __aenter__(self):
        return 42

    async def __aexit__(self, exc_type, exc, tb):
        pass


def test_sync():
    with CM() as x:
        assert x == 42


async def test_async():
    async with CM() as x:
        assert x == 42


test_sync()
asyncio.run(test_async())
```

# Comparisons

## `asyncio.run`

Unlike `asyncio.run`, an `AnySync` object can be `run()` even if an event loop is
already running.

For example, the following code will raise a `RuntimeError`:

```python
import asyncio


async def f():
    return 42


async def test_async():
    assert asyncio.run(f()) == 42


asyncio.run(test_async())
```

However, with AnySync, the following code will work as expected:

```python
import asyncio
from anysync import anysync


@anysync
async def f():
    return 42


async def test_async():
    assert f().run() == 42


asyncio.run(test_async())
```

## `unsync`

AnySync is similar to [`unsync`](https://pypi.org/project/unsync/) in that it allows
async functions to be called synchronously when needed. The main differences are that
AnySync works with type checkers, is lighter weight, works with other async libraries
like `trio` via `anyio`, in addition to supporting async generators and context
managers.

## Automatic Detection

The other approach to dealing with the challenges of mixing synchronous and asynchronous
code is to automatically infer whether a function should be run synchronously based on
whether it is being run in an async context. This approach is taken by libraries like
Prefect's
[`sync_compatible`](https://github.com/PrefectHQ/prefect/blob/934982e5969c1fd7721c06bbbb12b651ea0f2409/src/prefect/utilities/asyncutils.py#L335)
decorator. The main downside is that the behavior of the function changes dynamically
depending on the context which can lead to unexpected behavior.

For example, the code below works as expected beca

```python
from prefect.utilities.asyncutils import sync_compatible


@sync_compatible
async def request():
    ...
    return "hello"


def work():
    response = request()
    ...
    return response.upper()


def test_sync():
    assert work() == "HELLO"


test_sync()
```

However, if we now call `work()` from an async context, the behavior changes.

```python
import asyncio


async def test_async():
    assert work() == "HELLO"  # AttributeError: 'coroutine' object has no attribute 'upper'


asyncio.run(test_async())
```

Because `work()` is now being called from an async context, `request()` automatically
returns a coroutine object which causes `work()` to fail.

# Other Considerations

## How it Works

AnySync works by detecting the presence of a running event loop. If one already exists,
then AnySync uses a separate thread to run the coroutine. Where possible AnySync tries
to reuse a single global background thread that's created only when it's needed.
However, in the case that a program repeatedly trys to synchronously run a coroutine
while in an async context, AnySync will create a new thread each time.

For example, you can count the number of threads that are used in two different
scenarios. The first reuses the same global thread over and over again.

```python
from threading import current_thread

import anysync

threads = set()


@anysync.coroutine
async def f():
    threads.add(current_thread())  # runs in the main thread
    return g().run()


@anysync.coroutine
async def g():
    threads.add(current_thread())  # runs in anysync's global background thread
    return 42


f().run()
f().run()

main_thread = current_thread()
assert len(threads - {main_thread}) == 1
```

In the second scenario, ends up creating two threads in addition to AnySync's global
background thread because `g()` runs in the global background thread and `h()` runs in a
new thread each time.

```python
from threading import current_thread

import anysync

threads = set()


@anysync.coroutine
async def f():
    threads.add(current_thread())  # runs in the main thread
    return g().run()


@anysync.coroutine
async def g():
    threads.add(current_thread())  # runs in anysync's global background thread
    return h().run()


@anysync.coroutine
async def h():
    threads.add(current_thread())  # runs in a new thread each time
    return 42


f().run()
f().run()

main_thread = current_thread()
assert len(threads - {main_thread}) == 3
```

## Interacting with `contextvars`

AnySync wrapped coroutines or context managers will not propagate changes to
[`contextvars`](https://docs.python.org/3/library/contextvars.html) from async to
synchronous contexts. This is because `contextvars` are not shared between threads or
event loops and AnySync must create these in order to run coroutines synchronously.
Given this, the following is **not** supported:

```python
from contextvars import ContextVar
from anysync import anysync


var = ContextVar("var", default=0)


@anysync
async def f():
    var.set(42)


f().run()
assert var.get() == 42  # AssertionError: 0 != 42
```
