"""Cancel the main CLI task on console interruption on Linux and Windows."""

from contextlib import contextmanager
from dataclasses import dataclass
import signal
import sys
import threading


@dataclass
class CancellationSignals:
    received: int | None = None


@contextmanager
def cancel_on_signals(loop, task):
    """Restore previous handlers after bounded session cleanup has completed.

    Unix uses the event loop's signal wakeup mechanism. Windows uses
    signal.signal with its default Proactor loop's console wakeup support.
    SIGBREAK covers Windows console Ctrl+Break. Forced process termination
    cannot run Python cleanup handlers.
    """
    state = CancellationSignals()
    previous = {}

    def cancel(signum, frame):
        state.received = signum
        loop.call_soon_threadsafe(task.cancel)

    try:
        if threading.current_thread() is threading.main_thread():
            signals = [signal.SIGINT, signal.SIGTERM]
            if hasattr(signal, 'SIGBREAK'):
                signals.append(signal.SIGBREAK)
            for signum in signals:
                previous[signum] = signal.getsignal(signum)
                if sys.platform == 'win32':
                    signal.signal(signum, cancel)
                else:
                    loop.add_signal_handler(signum, cancel, signum, None)
        yield state
    finally:
        for signum, handler in previous.items():
            if sys.platform != 'win32':
                loop.remove_signal_handler(signum)
            signal.signal(signum, handler)
