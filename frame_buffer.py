"""Five seconds of timestamped JPEGs, bounded in time and memory per camera."""
from collections import deque

PRE_ROLL = 5
MAX_BYTES = 12 * 1024 * 1024


class FrameBuffer:
    def __init__(self):
        self.frames = deque()
        self.size = 0

    def append(self, stamp, image):
        self.frames.append((stamp,image));self.size+=len(image)
        while self.frames and (stamp-self.frames[0][0]>PRE_ROLL or self.size>MAX_BYTES):
            self.size-=len(self.frames.popleft()[1])

    def snapshot(self, now):
        return [(stamp,image) for stamp,image in self.frames if now-PRE_ROLL<=stamp<=now]

    def clear(self):
        self.frames.clear();self.size=0
