import time
import unittest
from unittest import mock

import call_fetcher
import config


class CallFetcherRecentSourceTest(unittest.TestCase):
    def test_recent_partial_d1_uses_aircall_direct_when_direct_has_more_calls(self):
        d1_rows = [{"call_id": "d1-1", "id": "d1-1"}]
        direct_rows = [{"call_id": "direct-1"}, {"call_id": "direct-2"}]

        with mock.patch.object(config, "AIRCALL_RECENT_DIRECT_COMPARE_DAYS", 2), \
             mock.patch.object(call_fetcher.d1_client, "fetch_call_history", return_value=d1_rows), \
             mock.patch.object(call_fetcher, "fetch_calls_range_aircall_direct", return_value=direct_rows) as direct:
            calls = call_fetcher.fetch_calls_range(int(time.time()) - 3600, int(time.time()))

        direct.assert_called_once()
        self.assertEqual(calls, direct_rows)

    def test_recent_d1_kept_when_aircall_direct_has_no_extra_calls(self):
        d1_rows = [{"call_id": "d1-1", "id": "d1-1"}, {"call_id": "d1-2", "id": "d1-2"}]
        direct_rows = [{"call_id": "direct-1"}]

        with mock.patch.object(config, "AIRCALL_RECENT_DIRECT_COMPARE_DAYS", 2), \
             mock.patch.object(call_fetcher.d1_client, "fetch_call_history", return_value=d1_rows), \
             mock.patch.object(call_fetcher, "fetch_calls_range_aircall_direct", return_value=direct_rows):
            calls = call_fetcher.fetch_calls_range(int(time.time()) - 3600, int(time.time()))

        self.assertEqual([call["call_id"] for call in calls], ["d1-1", "d1-2"])

    def test_old_d1_range_does_not_hit_aircall_direct(self):
        d1_rows = [{"call_id": "d1-1", "id": "d1-1"}]

        with mock.patch.object(config, "AIRCALL_RECENT_DIRECT_COMPARE_DAYS", 2), \
             mock.patch.object(call_fetcher.d1_client, "fetch_call_history", return_value=d1_rows), \
             mock.patch.object(call_fetcher, "fetch_calls_range_aircall_direct") as direct:
            calls = call_fetcher.fetch_calls_range(1000, 2000)

        direct.assert_not_called()
        self.assertEqual([call["call_id"] for call in calls], ["d1-1"])


if __name__ == "__main__":
    unittest.main()
