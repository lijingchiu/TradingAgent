"""Calendar execution checks for the preregistered UTC source family."""

from datetime import datetime, timezone
import unittest

import numpy as np

from research.intraday_breakout.run_utc_flow import clocks, decisions


def epoch(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())


class CalendarChecks(unittest.TestCase):
    def config(self, zone="Europe/London", hold=4, momentum=0):
        return {"timezone": zone, "holding_clock_hours": hold, "momentum_hours": momentum}

    def test_local_0800_observes_dst(self):
        for zone, timestamps in (
            ("Europe/London", ["2021-01-05T08:00:00", "2021-07-05T07:00:00"]),
            ("America/New_York", ["2021-01-05T13:00:00", "2021-07-05T12:00:00"]),
        ):
            times = np.array([epoch(value) for value in timestamps])
            _, allowed, _ = decisions(times, np.ones(2), self.config(zone), clocks(times, zone))
            np.testing.assert_array_equal(allowed, [True, True])

    def test_expiry_uses_the_observed_opening_clock(self):
        times = np.array([epoch("2021-01-05T11:45:00"), epoch("2021-01-05T12:00:00")])
        _, _, exits = decisions(times, np.ones(2), self.config(), clocks(times, "Europe/London"))
        self.assertTrue(exits[0])  # Engine consumes this at the observed 12:00 open.

    def test_long_data_gap_cannot_restart_old_holding_window(self):
        times = np.array([epoch("2021-01-08T08:00:00"), epoch("2021-01-11T08:00:00")])
        _, _, exits = decisions(times, np.ones(2), self.config(), clocks(times, "Europe/London"))
        self.assertTrue(exits[0])

    def test_future_prices_do_not_change_prior_momentum(self):
        times = np.arange(epoch("2021-01-05T00:00:00"), epoch("2021-01-06T00:00:00"), 900)
        close = np.linspace(1.1, 1.12, len(times))
        altered = close.copy()
        altered[50:] -= 0.1
        for momentum in (0, 1, 6):
            config = self.config(momentum=momentum)
            original = decisions(times, close, config, clocks(times, "Europe/London"))[0]
            changed = decisions(times, altered, config, clocks(times, "Europe/London"))[0]
            np.testing.assert_array_equal(original[:50], changed[:50])


if __name__ == "__main__":
    unittest.main()
