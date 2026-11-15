"""55-J regression: Uvicorn graceful timeout must terminate idle WSS and lifespan.

Loopback-only: does not create a public network route, read private TLS
material, touch GPIO, connect a device, or call AWS.
"""
import asyncio

import pytest
import uvicorn
import websockets


@pytest.mark.asyncio
async def test_55j_bounded_uvicorn_shutdown_closes_lifespan():
    shutdown_seen = asyncio.Event()
    entered_ws = asyncio.Event()

    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    shutdown_seen.set()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        elif scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.accept"})
            entered_ws.set()
            # Intentionally ignore connection close, to emulate ESP's
            # lingering WSS on Windows. Uvicorn must cancel this task.
            await asyncio.Event().wait()
        elif scope["type"] == "http":
            await send({"type": "http.response.start", "status": 404,
                        "headers": []})
            await send({"type": "http.response.body", "body": b""})

    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=0,
        ws="wsproto", lifespan="on", timeout_graceful_shutdown=1,
        access_log=False, log_level="critical",
    ))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started or task.done():
                break
            await asyncio.sleep(.02)
        assert server.started and server.servers
        port = server.servers[0].sockets[0].getsockname()[1]
        async with websockets.connect(
            f"ws://127.0.0.1:{port}/ws", open_timeout=3,
        ):
            await asyncio.wait_for(entered_ws.wait(), timeout=3)
            server.should_exit = True
            await asyncio.wait_for(task, timeout=8)
        assert task.done()
        assert shutdown_seen.is_set()
    finally:
        server.should_exit = True
        if not task.done():
            server.force_exit = True
            try:
                await asyncio.wait_for(task, timeout=8)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
