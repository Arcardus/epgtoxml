# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
import unittest

from Plugins.Extensions.EpgToXml.compat import wait_for_db_ready


class FakeClock(object):
    """Deterministische monotone Uhr; rueckt bei jedem sleep() vor."""

    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class WaitForDbReadyTests(unittest.TestCase):
    def test_ready_when_file_appears_and_size_stabilises(self):
        clock = FakeClock()
        # Datei taucht beim 2. Blick auf und stabilisiert sich beim 3./4. Blick.
        sizes = iter([None, 5000, 40000, 40000])
        states = []

        def exists(path):
            value = next(sizes)
            states.append(value)
            return value is not None

        def getsize(path):
            return states[-1]

        ok = wait_for_db_ready("/x/epg.db", 23 * 1024, timeout=100,
                               interval=1.0, exists=exists, getsize=getsize,
                               sleep=clock.sleep, clock=clock.time)
        self.assertTrue(ok)

    def test_times_out_when_file_never_appears(self):
        clock = FakeClock()
        ok = wait_for_db_ready("/x/epg.db", 23 * 1024, timeout=5,
                               interval=1.0, exists=lambda p: False,
                               getsize=lambda p: 0, sleep=clock.sleep,
                               clock=clock.time)
        self.assertFalse(ok)
        # Uhr ist bis ueber das Timeout gelaufen (kein Endlos-Loop).
        self.assertGreaterEqual(clock.now, 5)

    def test_times_out_when_size_stays_below_min(self):
        clock = FakeClock()
        ok = wait_for_db_ready("/x/epg.db", 23 * 1024, timeout=5,
                               interval=1.0, exists=lambda p: True,
                               getsize=lambda p: 100, sleep=clock.sleep,
                               clock=clock.time)
        self.assertFalse(ok)

    def test_oserror_during_poll_is_tolerated(self):
        clock = FakeClock()
        calls = {"n": 0}

        def getsize(path):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("vanished mid-write")
            return 40000

        ok = wait_for_db_ready("/x/epg.db", 23 * 1024, timeout=100,
                               interval=1.0, exists=lambda p: True,
                               getsize=getsize, sleep=clock.sleep,
                               clock=clock.time)
        # Nach dem stabilen 40000 ueber zwei Messungen -> ready.
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
