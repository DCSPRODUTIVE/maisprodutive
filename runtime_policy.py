"""Conservative concurrency and reconnect policy for small monitoring servers."""
import os
FIRST_FRAME_TIMEOUT=55
STALE_TIMEOUT=15
QUEUE_TIMEOUT=180
STABLE_RESET_SECONDS=30

def startup_parallelism(cpus=None):
    cpus=(os.cpu_count() or 1) if cpus is None else max(1,cpus)
    return 1 if cpus<=2 else 2 if cpus<=4 else 3

def encoder_parallelism(cpus=None):
    return 1 if ((os.cpu_count() or 1) if cpus is None else cpus)<=4 else 2
