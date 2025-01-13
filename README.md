# AnySync

[![PyPI - Version](https://img.shields.io/pypi/v/anysync.svg)](https://pypi.org/project/anysync)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

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

## Documentation

For more information, please see the [documentation](https://ryanmorshead.com/anysync).
