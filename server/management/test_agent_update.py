"""验证 Agent 版本接口与旧版单脚本下载内容保持一致。"""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from .views import AGENT_VERSION


class AgentUpdateTests(SimpleTestCase):
    def test_version_endpoint_matches_downloaded_single_file_agent(self):
        version = self.client.get('/api/agent/version/')
        download = self.client.get('/api/agent/download/')

        agent_dir = settings.BASE_DIR / 'device-agent'
        if not agent_dir.is_dir():
            agent_dir = settings.BASE_DIR.parent / 'device-agent'
        source = agent_dir / 'device-agent.py'
        script = download.content.decode('utf-8')
        self.assertEqual(version.status_code, 200)
        self.assertEqual(version.json()['version'], AGENT_VERSION)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(script, source.read_text(encoding='utf-8'))
        self.assertIn(f'AGENT_VERSION = "{AGENT_VERSION}"', script)
        compile(script, str(source), 'exec')
