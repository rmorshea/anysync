# anysync

A lightweight library for allowing async functions to be called in a synchronous manner.

```python
import asyncio
from anysync import anysync


@anysync
async def f():
    return 42


def test_sync():
    assert f().run() == 42


async def test_async():
    assert await f() == 42


test_sync()
asyncio.run(test_async())
```

`anysync` works by wrapping coroutines returned by async functions in an `AnySync`
object that can both be awaited and executed synchronously when calling its `run()`
method.

```python
from anysync import AnySync


async def f():
    return 42


coro = f()
assert AnySync(coro).run() == 42
```

## Comparison with `asyncio.run`

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

However, with `anysync`, the following code will work as expected:

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

This is accomplished by running the underlying coroutine in a separate thread.

## Comparison with `unsync`

`anysync` is similar to `unsync` in that it allows async functions to be called
synchronously when needed. The main differences are that `anysync` works with type
checkers, is lighter weight, and works with other async libraries like `trio` and
`curio` via `anyio`.

# Comparison with automatic detection

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
