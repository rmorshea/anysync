from anysync import AnySync, anysync


@anysync
async def wrapped():
    return "value"


async def unwrapped():
    return "value"


async def test_await_wrapped_function():
    assert await wrapped() == "value"


async def test_await_wrapped_coroutine():
    assert await AnySync(wrapped()) == "value"


def test_sync_wrapped_function():
    assert wrapped().run() == "value"


def test_sync_wrapped_coroutine():
    assert AnySync(wrapped()).run() == "value"


async def test_sync_wrapped_function_in_async_context():
    assert wrapped().run() == "value"


async def test_sync_wrapped_coroutine_in_async_context():
    assert AnySync(wrapped()).run() == "value"
