import asyncio
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import httpx
from websockets.asyncio.server import serve

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from profiles import ProfileStore, resolve_api_settings
from api_engine import ApiEngine,ApiError
from configuration import DEFAULT_CONFIG,validate_config
from bot import CatGirlBot


class ProfileTests(unittest.TestCase):
    def test_save_before_use_and_immutable_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ProfileStore(folder);cfg=deepcopy(DEFAULT_CONFIG)
            cfg['groups']['whitelist']=[123]
            with self.assertRaises(ValueError):validate_config(cfg,profile_store=store)
            record=store.create('测试',{'base_url':'https://example.test/v1','model':'test','api_key':'test-secret'})
            cfg['engine']['profile_id']=record.id;validate_config(cfg,profile_store=store)
            with self.assertRaises(TypeError):record.settings['model']='changed'
            with self.assertRaises(FrozenInstanceError):record.name='changed'
            self.assertFalse(hasattr(store,'update'))
            with self.assertRaises(ValueError):store.create('测试',{'base_url':'https://example.test','model':'other'})
            store.delete(record.id)
            with self.assertRaises(ValueError):validate_config(cfg,profile_store=store)

    def test_tampering_rejected_and_id_not_a_path(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ProfileStore(folder)
            record=store.create('test',{'base_url':'https://example.test','model':'test'})
            path=Path(folder)/(record.id+'.json');value=json.loads(path.read_text(encoding='utf-8'))
            value['settings']['model']='tampered';path.write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaises(ValueError):store.load(record.id)
            self.assertEqual(store.list(),[])
            with self.assertRaises(ValueError):store.delete('../outside')


class ProfileRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_deleted_profile_cannot_call_api(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ProfileStore(folder);cfg=deepcopy(DEFAULT_CONFIG)
            record=store.create('test',{'base_url':'https://example.test','model':'test'})
            cfg['engine']['profile_id']=record.id;called=[]
            def handler(request):called.append(request);return httpx.Response(200,json={})
            engine=ApiEngine(resolve_api_settings(cfg,store),httpx.MockTransport(handler))
            store.delete(record.id)
            with self.assertRaises(ApiError):await engine.generate('x','u',[])
            self.assertEqual(called,[])

    async def test_saved_key_is_not_overridden_by_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ProfileStore(folder);cfg=deepcopy(DEFAULT_CONFIG)
            cfg['engine']['profile_id']=store.create('test',{'base_url':'https://example.test','model':'test','api_key':'saved-secret'}).id
            headers=[]
            def handler(request):
                headers.append(request.headers.get('authorization'))
                return httpx.Response(200,json={'choices':[{'message':{'content':'hello'}}]})
            engine=ApiEngine(resolve_api_settings(cfg,store),httpx.MockTransport(handler))
            with patch.dict(os.environ,{'CATGIRL_API_KEY':'different-secret'}):await engine.generate('x','u',[])
            self.assertEqual(headers,['Bearer saved-secret'])

    async def test_delete_active_record_stops_standalone_bot(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ProfileStore(folder);cfg=deepcopy(DEFAULT_CONFIG)
            cfg['engine']['profile_id']=store.create('test',{'base_url':'https://example.test','model':'test'}).id
            connected=asyncio.Event()
            async def handler(socket):connected.set();await socket.wait_closed()
            async with serve(handler,'127.0.0.1',0) as server:
                cfg['onebot_url']=f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'
                bot=CatGirlBot(cfg,logging.getLogger('test'),profile_store=store)
                task=asyncio.create_task(bot.run_forever())
                try:
                    await asyncio.wait_for(connected.wait(),2)
                    store.delete(cfg['engine']['profile_id'])
                    await asyncio.wait_for(task,4)
                    self.assertIsNone(bot.bot.ws)
                finally:
                    task.cancel();await asyncio.gather(task,return_exceptions=True);await bot.bot.close()


if __name__=='__main__':unittest.main()
