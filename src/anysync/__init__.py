from importlib.metadata import PackageNotFoundError
from importlib.metadata import version

from anysync.core import AnySyncContextManager
from anysync.core import AnySyncCoroutine
from anysync.core import AnySyncGenerator
from anysync.core import contextmanager
from anysync.core import coroutine
from anysync.core import generator
from anysync.core import iterator
from anysync.core import run
from anysync.core import wrap_async_context_manager
from anysync.core import wrap_async_generator
from anysync.core import wrap_async_iterator
from anysync.core import wrap_coroutine

try:
    __version__ = version(__name__)
except PackageNotFoundError:  # nocov
    __version__ = "0.0.0"


__all__ = [
    "AnySyncContextManager",
    "AnySyncCoroutine",
    "AnySyncGenerator",
    "contextmanager",
    "coroutine",
    "generator",
    "iterator",
    "run",
    "wrap_async_context_manager",
    "wrap_async_generator",
    "wrap_async_iterator",
    "wrap_coroutine",
]
