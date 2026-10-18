import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import httpx

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api_engine import ApiEngine, ApiError
from catgirl import CatGirl
from configuration import DEFAULT_CONFIG, validate_config


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_selects_sticker_and_sends_full_context(self):
        captured=[]
        def handler(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({
                'messages':['哈？！','本喵生气了！'],'sticker_id':'local_test'})}}]})
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'cat.gif').write_bytes(b'GIF89a')
            (root/'catalog.json').write_text(json.dumps([{'id':'local_test','title':'炸毛猫','tags':['angry'],'file':'cat.gif'}]),encoding='utf-8')
            config={'llm':{'base_url':'https://example.test/v1','model':'test-model','api_key':'test-secret'},
                    'emotion_state_dir':root/'mood','sticker_state_dir':root/'history','sticker_dir':root}
            cat=CatGirl(config,transport=httpx.MockTransport(handler))
            entry={'user':'测试','user_id':1,'text':'猫娘发张生气表情包'}
            result=await cat.reply([entry],[entry],scope='test')
            self.assertEqual(result,'哈？！\n本喵生气了！')
            self.assertEqual(cat.reply_stickers['test'],'local_test')
            payload=json.loads(captured[0]['messages'][1]['content'])
            self.assertEqual(payload['sticker_choices'][0]['id'],'local_test')
            self.assertEqual(payload['reply_to']['text'],entry['text'])

    async def test_empty_library_still_replies(self):
        transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'choices':[{'message':{
            'content':'{"messages":["本喵来啦！"],"sticker_id":""}'}}]}))
        with tempfile.TemporaryDirectory() as folder:
            cat=CatGirl({'llm':{'base_url':'https://example.test','model':'test'},'sticker_dir':folder,
                         'emotion_state_dir':folder,'sticker_state_dir':folder},transport=transport)
            entry={'user':'测试','text':'猫娘你好'}
            self.assertEqual(await cat.reply([entry],[entry]),'本喵来啦！')
            self.assertFalse(cat.reply_stickers)

    async def test_http_errors_do_not_echo_secrets_or_body(self):
        for status in (400,401,403,404,429,500):
            with self.subTest(status=status):
                transport=httpx.MockTransport(lambda request:httpx.Response(status,text='test-secret private body'))
                engine=ApiEngine({'base_url':'https://example.test','model':'test','api_key':'test-secret'},transport)
                with self.assertRaises(ApiError) as caught:await engine.generate('x','u',[])
                self.assertIn(str(status),str(caught.exception))
                self.assertNotIn('test-secret',str(caught.exception))
                self.assertNotIn('private body',str(caught.exception))

    async def test_total_timeout_cancels_request(self):
        cancelled=asyncio.Event()
        async def handler(request):
            try:await asyncio.sleep(5)
            finally:cancelled.set()
            return httpx.Response(200,json={})
        engine=ApiEngine({'base_url':'https://example.test','model':'test','timeout':.03},httpx.MockTransport(handler))
        with self.assertRaises(ApiError):await engine.generate('x','u',[])
        self.assertTrue(cancelled.is_set())

    async def test_json_mode_is_opt_in(self):
        captured=[]
        def handler(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200,json={'choices':[{'message':{'content':'hello'}}]})
        engine=ApiEngine({'base_url':'https://example.test/v1/chat/completions','model':'test','json_mode':True},httpx.MockTransport(handler))
        self.assertEqual(await engine.generate('x','u',[]),'hello')
        self.assertEqual(captured[0]['response_format'],{'type':'json_object'})
        self.assertEqual(engine.endpoint(),'https://example.test/v1/chat/completions')


class ConfigurationTests(unittest.TestCase):
    def test_safe_defaults_and_validation(self):
        cfg=deepcopy(DEFAULT_CONFIG);cfg['engine']['llm'].update(base_url='https://example.test/v1',model='test')
        with self.assertRaises(ValueError):validate_config(cfg)
        cfg['groups']['whitelist']=[123];validate_config(cfg)
        self.assertFalse(cfg['privacy']['log_message_content'])
        self.assertEqual(cfg['reply']['trigger'],'mention_or_keyword')


if __name__=='__main__':unittest.main()
