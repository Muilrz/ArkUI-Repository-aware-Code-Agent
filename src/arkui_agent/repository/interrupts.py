"""Keep owned-resource cleanup finite despite repeated console interrupts."""
from contextlib import contextmanager
import signal
import threading


@contextmanager
def defer_keyboard_interrupt(*, reraise: bool = True):
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    interrupted = False

    def defer(signum, frame):
        nonlocal interrupted
        interrupted = True

    previous = signal.signal(signal.SIGINT, defer)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)
    if interrupted and reraise:
        raise KeyboardInterrupt
