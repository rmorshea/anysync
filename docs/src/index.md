# AnySync

[![PyPI - Version](https://img.shields.io/pypi/v/anysync.svg)](https://pypi.org/project/anysync)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight library that allows async functions to be called both synchronously and
asynchronously.

```python
import anysync


@anysync.coroutine
async def f():
    return 42


assert f().run() == 42


async def g():
    assert (await f()) == 42


anysync.run(g())
```

Just `pip install anysync` and you're good to go!

## Usage

### Coroutines

The primary use case for `anysync` is to allow async functions to be called in a
synchronous manner. All you need to do is add the `anysync.coroutine` decorator to your
async function:

```python
import anysync


@anysync.coroutine
async def f():
    return 42


assert f().run() == 42
```

You can also run an async function using `anysync.run`:

```python
import anysync


async def f():
    return 42


assert anysync.run(f()) == 42
```

!!! note

    See how `anysync.run` [compares to `asyncio.run`](#asynciorun)

### Iterators

You can also use `anysync` with async generators:

```python
import anysync


@anysync.iterator
async def gen():
    yield 1
    yield 2
    yield 3


assert list(gen()) == [1, 2, 3]
```

Note that in this case you don't need to call `run()`. The generator will automatically
detect how it's being used and run the coroutine accordingly.

### Generators

You can also use `anysync` with async generators:

```python
import anysync


@anysync.generator
async def gen():
    value = yield 1
    yield value


g = gen()
assert next(g) == 1
assert g.send(42) == 42
```

Note that in this case you don't need to call `run()`. The generator will automatically
detect how it's being used and run the coroutine accordingly.

### Context Managers

You can even use AnySync on your async context managers.

```python
import anysync


@anysync.contextmanager
async def cm():
    yield 42


with cm() as x:
    assert x == 42
```

You can alternatively subclass the `AnySyncContextManager` class:

```python
from anysync import AnySyncContextManager


class CM(AnySyncContextManager):
    async def __aenter__(self):
        return 42

    async def __aexit__(self, exc_type, exc, tb):
        pass


with CM() as x:
    assert x == 42
```

### Wrapping Existing Objects

You can convert existing coroutines, generators, iterators, or context managers into
AnySync object using the following functions:

- [`anysync.wrap_coroutine`](anysync.wrap_coroutine)
- [`anysync.wrap_generator`](anysync.wrap_generator)
- [`anysync.wrap_iterator`](anysync.wrap_iterator)
- [`anysync.wrap_context_manager`](anysync.wrap_context_manager)

This is useful if you have a one-off conversion and you want to avoid using the
decorator syntax.

```python
import anysync


async def f():
    return 42


wrapped_f = anysync.wrap_coroutine(f)
assert wrapped_f().run() == 42
```

## Comparisons

### `asyncio.run`

Unlike `asyncio.run`, an `AnySync` object can be `run()` even if an event loop is
already active.

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
import anysync


async def f():
    return 42


async def test_async():
    assert anysync.run(f()) == 42


anysync.run(test_async())
```

### `unsync`

AnySync is similar to [`unsync`](https://pypi.org/project/unsync/) in that it allows
async functions to be called synchronously when needed. The main differences are that
AnySync works with type checkers and other async libraries like `trio` via `anyio` as
well as async generators and context managers.

### Automatic Detection

The other approach to dealing with the challenges of mixing synchronous and asynchronous
code is to automatically infer whether a function should be run synchronously based on
whether it is being run in an async context. This approach is taken by libraries like
Prefect's
[`sync_compatible`](https://github.com/PrefectHQ/prefect/blob/934982e5969c1fd7721c06bbbb12b651ea0f2409/src/prefect/utilities/asyncutils.py#L335)
decorator. The main downside is that the behavior of the function changes dynamically
depending on the context which can lead to unexpected behavior.

For example, the code below operates as expected where `work()` is called in a sync
context:

```python
from prefect.utilities.asyncutils import sync_compatible


@sync_compatible
async def request():
    return "hello"


def work():
    response = request()
    return response.upper()


def test_sync():
    assert work() == "HELLO"


test_sync()
```

However, if we now call `work()` from an async context, the behavior changes:

<!-- skip doccmd[all]: next -->

```python
import asyncio


async def test_async():
    assert work() == "HELLO"  # AttributeError: 'coroutine' object has no attribute 'upper'


asyncio.run(test_async())
```

Because `work()` is now being called from an async context, `request()` automatically
returns a coroutine object which causes `work()` to fail.

## Other Considerations

### How it Works

AnySync works by detecting the presence of a running event loop. If one already exists,
then AnySync uses a separate thread to run the coroutine. Where possible AnySync tries
to reuse a single global background thread that's created only when it's needed.
However, in the case that a program repeatedly trys to synchronously run a coroutine
while in an async context, AnySync will create a new thread each time.

#### Background Thread Reuse

The script below counts the number of threads that AnySync spawns when calling `f`
twice.

- The function `f` runs in the main thread
- The function `g`, when called by `f` runs in AnySync's global background thread

Thus, even though `f` is called more than once we see that AnySync only spawns one
thread for both.

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

#### Background Thread Spawning

As above, the script below counts the number of threads that AnySync spawns when calling
`f` twice. In this case though

- `f` runs in the main thread
- `g`, when called by `f`, runs in AnySync's global background thread
- `h`, when called by `g`, runs in a new thread each time it's called

Thus, we end up counting three threads, 1 for the global background thread used to run
`g` and 2 more for each call `g` makes into `h`.

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

### Interacting with `contextvars`

AnySync wrapped coroutines or context managers will not propagate changes to
[`contextvars`](https://docs.python.org/3/library/contextvars.html) from async to
synchronous contexts. This is because `contextvars` are not shared between threads or
event loops and AnySync must create these in order to run coroutines synchronously.
Given this, the following is **not** supported:

```python
from contextvars import ContextVar

import anysync

var = ContextVar("var", default=0)


@anysync.coroutine
async def f():
    var.set(42)


f().run()
assert var.get() == 42  # AssertionError: 0 != 42
```
