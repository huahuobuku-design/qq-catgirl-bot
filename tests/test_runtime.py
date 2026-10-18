import asyncio
from copy import deepcopy
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bot import CatGirlBot
from configuration import DEFAULT_CONFIG
from runtime_guard import InstanceLock
from profiles import ProfileStore


class RuntimeTests(unittest.TestCase):
    def test_duplicate_instance_excluded_and_lock_released(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bot.lock';lock=InstanceLock(path);self.assertTrue(lock.acquire())
            code='import sys;from runtime_guard import InstanceLock;x=InstanceLock(sys.argv[1]);print(x.acquire());x.close()'
            def probe():return subprocess.run([sys.executable,'-c',code,str(path)],cwd=Path(__file__).parents[1],capture_output=True,text=True,check=True).stdout.strip()
            self.assertEqual(probe(),'False');lock.close();self.assertEqual(probe(),'True')


class PermissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory()
        store=ProfileStore(self.directory.name)
        profile=store.create('test',{'base_url':'https://example.test/v1','model':'test'})
        cfg=deepcopy(DEFAULT_CONFIG);cfg['groups']['whitelist']=[123]
        cfg['engine']['profile_id']=profile.id
        self.bot=CatGirlBot(cfg,logging.getLogger('test'),profile_store=store)
        self.worker=Mock();self.worker.muted=False;self.bot.get_worker=Mock(return_value=self.worker)

    async def asyncTearDown(self):self.directory.cleanup()

    def event(self,text,role='member',mid=1):
        return {'post_type':'message','message_type':'group','group_id':123,'user_id':456,'self_id':999,
                'message_id':mid,'raw_message':text,'sender':{'nickname':'test','role':role}}

    async def test_empty_whitelist_is_not_all_groups(self):
        self.bot.whitelist=set();self.assertFalse(self.bot.group_allowed(123))

    async def test_only_keyword_or_mention_triggers(self):
        await self.bot.on_event(self.event('你好'));self.worker.feed.assert_not_called()
        await self.bot.on_event(self.event('猫娘你好',mid=2));self.worker.feed.assert_called_once()

    async def test_member_cannot_mute_but_admin_can(self):
        await self.bot.on_event(self.event('猫娘闭嘴'));self.assertFalse(self.worker.muted)
        await self.bot.on_event(self.event('猫娘闭嘴',role='admin',mid=2));self.assertTrue(self.worker.muted)

    async def test_self_and_duplicate_events_ignored(self):
        event=self.event('猫娘你好');await self.bot.on_event(event);await self.bot.on_event(event)
        self.worker.feed.assert_called_once()
        event=self.event('猫娘你好',mid=2);event['user_id']=999;await self.bot.on_event(event)
        self.worker.feed.assert_called_once()


if __name__=='__main__':unittest.main()
