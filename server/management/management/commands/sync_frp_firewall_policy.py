from django.core.management.base import BaseCommand

from management.frp_firewall import publish_frp_firewall_policy
from management.views import get_frp_config


class Command(BaseCommand):
    help = 'Publish the current FRP port access policy to the host updater.'

    def handle(self, *args, **options):
        state = publish_frp_firewall_policy(get_frp_config())
        if state['state'] == 'error':
            self.stderr.write(self.style.ERROR(f"FRP 防火墙策略暂未应用：{state['error']}"))
            return
        if state['state'] == 'unavailable':
            self.stderr.write(self.style.WARNING('宿主防火墙控制器尚未连接，FRP 规则快照未确认应用。'))
            return
        self.stdout.write(f"FRP 防火墙策略已提交：revision {state['requested_revision']}")
