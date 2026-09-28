import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class KeyedLocks:
    """按 key 复用 asyncio.Lock，用于缓存的 single-flight。

    key 可能来自不可信输入（客户端随便编的 token），所以锁表必须有上界，
    否则它本身就是个内存放大点。上界在"锁全部被同时持有"的极端并发下会
    临时被突破到并发峰值，随下一次调用回落——这是有意的取舍。
    """

    def __init__(self, maxsize: int = 1024) -> None:
        self._maxsize = maxsize
        self._locks: OrderedDict[str, asyncio.Lock] = OrderedDict()

    @asynccontextmanager
    async def hold(self, key: str) -> AsyncIterator[None]:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        self._locks.move_to_end(key)
        self._evict()
        async with lock:
            yield

    def _evict(self) -> None:
        while len(self._locks) > self._maxsize:
            key, lock = self._locks.popitem(last=False)
            if lock.locked():
                # 正在被持有：放回队尾，本轮不再尝试淘汰它
                self._locks[key] = lock
                return
