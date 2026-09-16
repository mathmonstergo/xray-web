from tests import support

import asyncio
from contextlib import contextmanager
import threading
import time
import unittest
from unittest.mock import patch

from core import speedtest
from core.test_stream import test_stream_response


class Response:
    status_code = 200
    def __init__(self, chunks): self.chunks = chunks
    def __enter__(self): return self
    def __exit__(self, *args): self.closed = True
    def iter_content(self, chunk_size): yield from self.chunks()


class SpeedTests(unittest.TestCase):
    def test_cancelled_download_never_starts_request(self):
        event = threading.Event()
        event.set()
        with patch.object(speedtest.requests, "get") as get:
            with self.assertRaises(speedtest.CancelledError):
                speedtest.stream_speed({}, cancel_event=event)
            get.assert_not_called()

    def test_mid_download_cancel_does_not_retry_or_report_timeout(self):
        event = threading.Event()
        def chunks():
            event.set()
            yield b"fixture"
        response = Response(chunks)
        with patch.object(speedtest.requests, "get", return_value=response) as get:
            with self.assertRaises(speedtest.CancelledError):
                speedtest.stream_speed({}, cancel_event=event)
            self.assertEqual(get.call_count, 1)
            self.assertTrue(response.closed)

    def test_cancel_during_timeout_does_not_try_another_url(self):
        event = threading.Event()
        def get(*args, **kwargs):
            event.set()
            raise speedtest.requests.Timeout()
        with patch.object(speedtest.requests, "get", side_effect=get) as mocked:
            with self.assertRaises(speedtest.CancelledError):
                speedtest.stream_speed({}, cancel_event=event)
            self.assertEqual(mocked.call_count, 1)

    def test_short_download_reports_true_average(self):
        response = Response(lambda: iter([b"x" * (1024 * 1024)]))
        moments = iter([0, 0.5, 0.5, 0.5])
        with patch.object(speedtest.requests, "get", return_value=response), patch.object(speedtest.time, "monotonic", side_effect=lambda: next(moments)):
            ok, measured, _ = speedtest.stream_speed({}, timeout=10, warmup=1)
        self.assertTrue(ok)
        self.assertEqual(measured, "2.0 MB/s")

    def test_limit_is_shared_between_independent_calls(self):
        active = maximum = 0
        lock = threading.Lock()
        @speedtest.limited_test(True)
        def work(node_id, **kwargs):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(active, maximum)
            time.sleep(0.03)
            with lock: active -= 1
        with patch.dict(speedtest._test_slots, {True: threading.BoundedSemaphore(1)}):
            threads = [threading.Thread(target=work, args=(str(i),)) for i in range(3)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=2)
        self.assertEqual(maximum, 1)
        self.assertFalse(any(thread.is_alive() for thread in threads))

    def test_waiting_for_slot_can_be_cancelled(self):
        semaphore = threading.BoundedSemaphore(1)
        semaphore.acquire()
        event = threading.Event()
        entered = []
        @speedtest.limited_test(True)
        def work(node_id, **kwargs): entered.append(node_id)
        event.set()
        with patch.dict(speedtest._test_slots, {True: semaphore}):
            with self.assertRaises(speedtest.CancelledError): work("fixture", cancel_event=event)
        semaphore.release()
        self.assertEqual(entered, [])

    def test_cancelled_batch_accounts_for_all_unique_nodes(self):
        event = threading.Event()
        event.set()
        with patch.object(speedtest, "test_node_speed") as worker, patch.object(speedtest.store, "save") as save:
            events = list(speedtest.iter_batch_progress(["a", "a", "b"], speed=True, cancel_event=event))
            worker.assert_not_called()
            save.assert_called_once()
        complete = events[-1]
        self.assertEqual(complete["type"], "complete")
        self.assertEqual(complete["total"], 2)
        self.assertEqual({r["node_id"] for r in complete["results"]}, {"a", "b"})
        self.assertTrue(all(r["cancelled"] for r in complete["results"]))

    def test_active_node_probe_uses_an_isolated_core(self):
        called = []
        @contextmanager
        def temporary(node, cancel_event=None):
            called.append(node)
            yield {"http": "fixture"}
        with patch.object(speedtest, "_temporary_core", temporary):
            with speedtest._proxies_for_node({"is_active": True}) as proxies:
                self.assertEqual(proxies["http"], "fixture")
        self.assertEqual(len(called), 1)


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_closing_response_cancels_its_worker(self):
        finished = threading.Event()
        observed = []
        def worker(ids, **kwargs):
            event = kwargs["cancel_event"]
            observed.append(event)
            event.wait(timeout=2)
            finished.set()
            yield {"type": "complete", "results": []}
        response = test_stream_response(["fixture"], speed=True, worker=worker)
        iterator = response.body_iterator
        first = await iterator.__anext__()
        self.assertIn('"type": "start"', first)
        await iterator.aclose()
        self.assertTrue(finished.wait(timeout=1))
        self.assertTrue(observed[0].is_set())
