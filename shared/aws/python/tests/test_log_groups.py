from __future__ import annotations

import unittest

from aws.log_groups import build_device_log_group_name, build_rig_log_group_name


class LogGroupNameTests(unittest.TestCase):
    def test_build_rig_log_group_name_uses_thing_ids(self) -> None:
        self.assertEqual(
            build_rig_log_group_name(
                town_thing_name="town-3xvtqf",
                rig_thing_name="rig-rig001",
            ),
            "txing/town-3xvtqf/rig-rig001",
        )

    def test_build_device_log_group_name_appends_device_thing_name(self) -> None:
        self.assertEqual(
            build_device_log_group_name(
                town_thing_name="town-3xvtqf",
                rig_thing_name="rig-rig001",
                device_thing_name="unit-bfk8gv",
            ),
            "txing/town-3xvtqf/rig-rig001/unit-bfk8gv",
        )


if __name__ == "__main__":
    unittest.main()
