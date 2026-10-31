"""Numeric Linux health counters; never inspect arguments or environment secrets."""
from pathlib import Path
import os


def snapshot(root=Path('/proc')):
    result={}
    try:
        result['boot_uptime_seconds']=round(float((root/'uptime').read_text().split()[0]))
        values=dict(line.split() for line in (root/'vmstat').read_text().splitlines())
        result['oom_kills_since_boot']=int(values.get('oom_kill',0))
    except (OSError,ValueError,IndexError):pass
    pending=[os.getpid()];seen=set();rss=threads=0
    while pending and len(seen)<256:
        pid=pending.pop()
        if pid in seen:continue
        seen.add(pid)
        try:
            status={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in (root/str(pid)/'status').read_text().splitlines() if ':' in line}
            rss+=int(status.get('VmRSS','0').split()[0]);threads+=int(status.get('Threads','0'))
            children=(root/str(pid)/'task'/str(pid)/'children').read_text().split()
            pending.extend(int(value) for value in children if value.isdecimal())
        except (OSError,ValueError):pass
    result.update(known_process_count=len(seen),known_process_threads=threads,known_rss_mib=round(rss/1024))
    for resource in ('cpu','memory','io'):
        try:
            for line in (root/'pressure'/resource).read_text().splitlines():
                tokens=line.split();values=dict(token.split('=') for token in tokens[1:])
                if tokens[0] in ('some','full'):result[f'{resource}_{tokens[0]}_pressure_avg10']=float(values['avg10'])
        except (OSError,ValueError,KeyError):pass
    return result
