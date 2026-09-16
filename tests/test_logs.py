from tests import support

import asyncio
from pathlib import Path
import tempfile
import unittest

from core.logs import tail_lines, follow_log


class LogTests(unittest.IsolatedAsyncioTestCase):
    async def test_tail_reads_last_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "access.log"
            path.write_text("".join(f"line-{i}\n" for i in range(1000)))
            self.assertEqual(tail_lines(path, 2), ["line-998", "line-999"])

    async def test_follow_reopens_after_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "access.log"
            path.write_text("old-line\n")
            stream = follow_log(path)
            self.assertIn("old-line", await stream.__anext__())
            path.rename(path.with_suffix(".old"))
            path.write_text("new-line\n")
            self.assertIn("new-line", await asyncio.wait_for(stream.__anext__(), 2))
            await stream.aclose()

    async def test_missing_log_reports_and_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "access.log"
            stream = follow_log(path)
            self.assertIn("stream-error", await stream.__anext__())
            path.write_text("new-line\n")
            self.assertIn('"ready": true', await asyncio.wait_for(stream.__anext__(), 2))
            self.assertIn("new-line", await stream.__anext__())
            await stream.aclose()
