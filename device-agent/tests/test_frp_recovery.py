"""覆盖 FRP 本机服务失效时的重新下发信号与自启恢复。"""

from subprocess import CompletedProcess, TimeoutExpired
import unittest
from unittest.mock import mock_open, patch

from .test_log_tasks import load_agent


class FrpRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.agent = load_agent()

    def test_heartbeat_invalidate_only_confirmed_local_service_faults(self):
        cases = (
            ("active", "enabled", 5),
            ("activating", "enabled", 5),
            ("inactive", "enabled", 0),
            ("failed", "enabled", 0),
            ("active", "disabled", 0),
        )
        for active_state, unit_state, expected in cases:
            with self.subTest(active_state=active_state, unit_state=unit_state):
                stdout = f"ActiveState={active_state}\nUnitFileState={unit_state}\n"
                with (
                    patch("builtins.open", mock_open(read_data="5")),
                    patch.object(self.agent.subprocess, "run", return_value=CompletedProcess([], 0, stdout)),
                ):
                    self.assertEqual(self.agent.get_local_frp_config_version(), expected)

    def test_unavailable_systemd_status_does_not_trigger_restart(self):
        with (
            patch("builtins.open", mock_open(read_data="5")),
            patch.object(self.agent.subprocess, "run", side_effect=TimeoutExpired("systemctl", 3)),
        ):
            self.assertEqual(self.agent.get_local_frp_config_version(), 5)

    def test_existing_disabled_service_is_enabled_without_rewriting_unit(self):
        with (
            patch.object(self.agent.os.path, "exists", return_value=True),
            patch("builtins.open", mock_open()) as unit,
            patch.object(self.agent.subprocess, "run") as systemctl,
        ):
            self.assertTrue(self.agent.ensure_frpc_service())
        unit.assert_not_called()
        systemctl.assert_called_once_with(["systemctl", "enable", "frpc"], check=True, timeout=30)
