"""Host FRP firewall rules stay scoped to updater-owned ports and comments."""
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

try:
    import fcntl  # noqa: F401
except ModuleNotFoundError:
    sys.modules['fcntl'] = types.SimpleNamespace(LOCK_EX=1, LOCK_NB=2, LOCK_UN=4, flock=lambda *_args: None)

from daemon import FirewallError, apply_firewall_policy, validate_firewall_policy


def policy(*, public_access=False, devices=None):
    return {
        'schema_version': 1,
        'revision': 7,
        'port_pool_start': 11000,
        'port_pool_end': 11999,
        'devices': devices if devices is not None else [{
            'device_id': 'DEV-test-1',
            'ssh_port': 11260,
            'web_port': 11261,
            'public_access': public_access,
        }],
    }


class FirewallPolicyTests(unittest.TestCase):
    def test_policy_rejects_conflicts_and_invalid_device_ids(self):
        duplicate = {
            'device_id': 'DEV-test-2', 'ssh_port': 11261, 'web_port': 11262,
            'public_access': False,
        }
        with self.assertRaisesRegex(FirewallError, 'conflicting'):
            validate_firewall_policy(policy(devices=[policy()['devices'][0], duplicate]))

        invalid_id = {
            'device_id': 'DEV-test;touch-/tmp/pwned', 'ssh_port': 11260,
            'web_port': 11261, 'public_access': True,
        }
        with self.assertRaisesRegex(FirewallError, 'Invalid or conflicting'):
            validate_firewall_policy(policy(devices=[invalid_id]))

    def test_public_access_adds_exact_ipv4_and_ipv6_accept_rules(self):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            if args[1] == '-C':
                return subprocess.CompletedProcess(args, 1, '', 'rule not found')
            if args[1] == '-S':
                return subprocess.CompletedProcess(args, 0, '', '')
            return subprocess.CompletedProcess(args, 0, '', '')

        with patch('daemon.subprocess.run', side_effect=run):
            result = apply_firewall_policy(policy(public_access=True))

        self.assertEqual(result, {'revision': 7, 'rule_count': 4})
        inserts = [args for args in calls if args[1] == '-I']
        self.assertEqual(len(inserts), 4)
        self.assertEqual({args[0] for args in inserts}, {'iptables', 'ip6tables'})
        self.assertTrue(all(args[2:5] == ['INPUT', '1', '!'] for args in inserts))
        self.assertEqual({args[args.index('--dport') + 1] for args in inserts}, {'11260', '11261'})
        self.assertTrue(all(args[args.index('-j') + 1] == 'ACCEPT' for args in inserts))

    def test_private_access_drops_only_non_loopback_traffic(self):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            if args[1] == '-C':
                return subprocess.CompletedProcess(args, 1, '', 'rule not found')
            if args[1] == '-S':
                return subprocess.CompletedProcess(args, 0, '', '')
            return subprocess.CompletedProcess(args, 0, '', '')

        with patch('daemon.subprocess.run', side_effect=run):
            apply_firewall_policy(policy(public_access=False))

        inserts = [args for args in calls if args[1] == '-I']
        self.assertEqual(len(inserts), 4)
        self.assertTrue(all(args[2:5] == ['INPUT', '1', '!'] for args in inserts))
        self.assertTrue(all(args[args.index('-i') + 1] == 'lo' for args in inserts))
        self.assertTrue(all(args[args.index('-j') + 1] == 'DROP' for args in inserts))

    def test_ipv6_failure_rolls_back_ipv4_rules_added_by_the_same_policy(self):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            if args[1] == '-C':
                return subprocess.CompletedProcess(args, 1, '', 'rule not found')
            if args[1] == '-I' and args[0] == 'ip6tables':
                return subprocess.CompletedProcess(args, 1, '', 'IPv6 firewall unavailable')
            return subprocess.CompletedProcess(args, 0, '', '')

        with patch('daemon.subprocess.run', side_effect=run):
            with self.assertRaisesRegex(FirewallError, 'IPv6 firewall unavailable'):
                apply_firewall_policy(policy(public_access=True))

        ipv4_accepts = [args for args in calls if args[0] == 'iptables' and args[1] == '-I']
        ipv4_rollbacks = [args for args in calls if args[0] == 'iptables' and args[1] == '-D']
        self.assertEqual(len(ipv4_accepts), 2)
        self.assertEqual(len(ipv4_rollbacks), 2)

    def test_cleanup_removes_only_exact_rules_owned_by_this_controller(self):
        stale = (
            '-A INPUT ! -i lo -p tcp --dport 11260 -m comment '
            '--comment dmp-frp-private-DEV-test-1-11260 -j DROP\n'
        )
        unrelated = (
            '-A INPUT ! -i lo -p tcp -m multiport --dports 11260,11261 '
            '-m comment --comment jetson-dev-DEV-test-1-acceptance -j DROP\n'
        )
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            if args[1] == '-C':
                return subprocess.CompletedProcess(args, 1, '', 'rule not found')
            if args[1] == '-S':
                return subprocess.CompletedProcess(args, 0, stale + unrelated, '')
            return subprocess.CompletedProcess(args, 0, '', '')

        with patch('daemon.subprocess.run', side_effect=run):
            apply_firewall_policy(policy(public_access=True))

        deletes = [args for args in calls if args[1] == '-D']
        self.assertEqual(len(deletes), 2)
        delete_text = [' '.join(args) for args in deletes]
        self.assertTrue(all('dmp-frp-private-' in args for args in delete_text))
        self.assertFalse(any('jetson-dev-' in args for args in delete_text))


if __name__ == '__main__':
    unittest.main()
