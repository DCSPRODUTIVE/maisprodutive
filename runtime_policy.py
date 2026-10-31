"""Conservative concurrency and reconnect policy for small monitoring servers."""
import os
FIRST_FRAME_TIMEOUT=55
STALE_TIMEOUT=15
QUEUE_TIMEOUT=180
STABLE_RESET_SECONDS=30

def startup_parallelism(cpus=None):
    cpus=(os.cpu_count() or 1) if cpus is None else max(1,cpus)
    return 1 if cpus<=4 else 2 if cpus<=8 else 3

def encoder_parallelism(cpus=None):
    return 1 if ((os.cpu_count() or 1) if cpus is None else cpus)<=4 else 2


def background_priority(process):
    # Decoder/encoder helpers yield to the host UI and HTTP service under load.
    try:
        if hasattr(os,'setpriority') and os.getpriority(os.PRIO_PROCESS,process.pid)<5:
            os.setpriority(os.PRIO_PROCESS,process.pid,5)
    except (OSError,AttributeError):pass
