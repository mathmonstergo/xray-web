"""Request-scoped SSE cancellation, independent of generator garbage collection."""

import asyncio
import json
import threading
import uuid

from fastapi.responses import StreamingResponse


def test_stream_response(node_ids, *, speed, worker):
    ids = list(dict.fromkeys(node_ids))
    cancel_event = threading.Event()
    test_id = uuid.uuid4().hex

    async def events():
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        def publish(value):
            if cancel_event.is_set():
                return
            try:
                loop.call_soon_threadsafe(queue.put_nowait, value)
            except RuntimeError:
                cancel_event.set()

        def run():
            try:
                for event in worker(ids, speed=speed, persist=False, cancel_event=cancel_event):
                    publish(event)
            except Exception as exc:
                publish({"type": "error", "message": str(exc)})
            finally:
                publish(None)

        producer = threading.Thread(target=run, name=f"xray-test-{test_id[:8]}", daemon=True)
        producer.start()
        try:
            yield f"data: {json.dumps({'type': 'start', 'test_id': test_id, 'total': len(ids)})}\n\n"
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps({**event, 'test_id': test_id}, ensure_ascii=False)}\n\n"
                if event.get("type") in ("complete", "error"):
                    break
        finally:
            cancel_event.set()

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })
