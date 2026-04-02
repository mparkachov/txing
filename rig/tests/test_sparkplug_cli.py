from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from rig.sparkplug_cmd import _parse_args as parse_cmd_args
from rig.sparkplug_log import _parse_args as parse_log_args


class SparkplugCliTests(unittest.TestCase):
    def test_sparkplug_cmd_uses_sdk_environment_without_endpoint_flags(self) -> None:
        with patch.dict(
            os.environ,
            {
                "THING_NAME": "txing-prod",
                "SPARKPLUG_GROUP_ID": "town-prod",
                "SPARKPLUG_EDGE_NODE_ID": "rig-prod",
            },
            clear=True,
        ):
            with patch("sys.argv", ["rig-sparkplug-cmd", "--redcon", "3"]):
                args = parse_cmd_args()

        self.assertEqual(args.thing_name, "txing-prod")
        self.assertEqual(args.sparkplug_group_id, "town-prod")
        self.assertEqual(args.sparkplug_edge_node_id, "rig-prod")
        self.assertFalse(hasattr(args, "iot_endpoint"))
        self.assertFalse(hasattr(args, "iot_endpoint_file"))
        self.assertFalse(hasattr(args, "cert_file"))
        self.assertFalse(hasattr(args, "key_file"))
        self.assertFalse(hasattr(args, "ca_file"))

    def test_sparkplug_log_uses_sdk_environment_without_endpoint_flags(self) -> None:
        with patch.dict(
            os.environ,
            {
                "THING_NAME": "txing-prod",
                "SPARKPLUG_GROUP_ID": "town-prod",
                "SPARKPLUG_EDGE_NODE_ID": "rig-prod",
            },
            clear=True,
        ):
            with patch("sys.argv", ["rig-sparkplug-log"]):
                args = parse_log_args()

        self.assertEqual(args.thing_name, "txing-prod")
        self.assertEqual(args.sparkplug_group_id, "town-prod")
        self.assertEqual(args.sparkplug_edge_node_id, "rig-prod")
        self.assertFalse(hasattr(args, "iot_endpoint"))
        self.assertFalse(hasattr(args, "iot_endpoint_file"))
        self.assertFalse(hasattr(args, "cert_file"))
        self.assertFalse(hasattr(args, "key_file"))
        self.assertFalse(hasattr(args, "ca_file"))


if __name__ == "__main__":
    unittest.main()
