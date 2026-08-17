import asyncio
from pathlib import Path

import pytest

from serena_skill_cli.locking import FileLock


@pytest.mark.asyncio
async def test_async_lock_wait_does_not_block_event_loop(tmp_path: Path):
    path = tmp_path / "server.lock"
    holder_ready = asyncio.Event()
    release_holder = asyncio.Event()
    waiter_acquired = asyncio.Event()

    async def holder():
        async with FileLock(path, timeout=1.0, poll_interval=0.01):
            holder_ready.set()
            await release_holder.wait()

    async def waiter():
        await holder_ready.wait()
        async with FileLock(path, timeout=1.0, poll_interval=0.01):
            waiter_acquired.set()

    holder_task = asyncio.create_task(holder())
    waiter_task = asyncio.create_task(waiter())
    await holder_ready.wait()
    await asyncio.sleep(0.05)
    release_holder.set()
    await asyncio.wait_for(waiter_acquired.wait(), timeout=0.5)
    await asyncio.gather(holder_task, waiter_task)
