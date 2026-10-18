"""Synthetic OneBot WebSocket -> API adapter -> text + GIF delivery."""
import asyncio
import base64
from copy import deepcopy
import json
import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock
import httpx
from PIL import Image
from websockets.asyncio.server import serve

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bot import CatGirlBot, GroupWorker, OneBot
from configuration import DEFAULT_CONFIG
from import_stickers import build_catalog
from profiles import ProfileStore


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_text_burst_and_gif_through_onebot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pack=root/'pack';pack.mkdir()
            frames=[Image.new('RGB',(32,32),color) for color in ('red','blue')]
            frames[0].save(pack/'委屈猫.gif',save_all=True,append_images=frames[1:],duration=100,loop=0)
            build_catalog(pack)
            received=[];delivered=asyncio.Event()
            async def handler(socket):
                await socket.send(json.dumps({'post_type':'message','message_type':'group','group_id':123,
                    'user_id':456,'self_id':999,'message_id':1,'raw_message':'猫娘发张委屈表情包',
                    'sender':{'nickname':'test','role':'member'}}))
                async for raw in socket:
                    request=json.loads(raw)
                    if request['action']=='send_group_msg':
                        received.append(request['params']['message'])
                        await socket.send(json.dumps({'echo':request['echo'],'status':'ok','retcode':0,'data':{'message_id':len(received)}}))
                        if len(received)==3:delivered.set()
            def api(request):
                payload=json.loads(json.loads(request.content)['messages'][1]['content'])
                chosen=payload['sticker_choices'][0]['id']
                return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({
                    'messages':['不许凶本喵！','给你看一眼，呜呜。'],'sticker_id':chosen})}}]})
            cfg=deepcopy(DEFAULT_CONFIG);cfg['groups']['whitelist']=[123]
            cfg['reply'].update(debounce_seconds=0,max_wait_seconds=0,min_interval_seconds=0)
            cfg['engine'].update(sticker_dir=str(pack),sticker_state_dir=str(root/'history'),emotion_state_dir=str(root/'mood'))
            store=ProfileStore(root/'profiles')
            cfg['engine']['profile_id']=store.create('test',{'base_url':'https://example.test/v1','model':'test'}).id
            async with serve(handler,'127.0.0.1',0) as server:
                cfg['onebot_url']=f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'
                bot=CatGirlBot(cfg,logging.getLogger('integration'),profile_store=store)
                bot.cat.llm.transport=httpx.MockTransport(api)
                task=asyncio.create_task(bot.run_forever())
                try:
                    await asyncio.wait_for(delivered.wait(),5)
                    self.assertEqual(received[:2],['不许凶本喵！','给你看一眼，呜呜。'])
                    image=received[2][0]
                    self.assertEqual(image['type'],'image')
                    self.assertTrue(base64.b64decode(image['data']['file'][9:]).startswith(b'GIF'))
                finally:
                    task.cancel()
                    await asyncio.gather(task,return_exceptions=True)
                    await bot.bot.close()

    async def test_slow_generation_acknowledges_and_respects_burst_limit(self):
        class Cat:
            name='猫娘'
            reply_stickers={}
            class Stickers:
                def get(self,value):return None
            stickers=Stickers()
            async def reply(self,history,focus,scope='local'):
                await asyncio.sleep(.04)
                return '想好了！\n原来是这样。\n本喵真聪明！'
        cfg=deepcopy(DEFAULT_CONFIG)
        cfg['reply'].update(debounce_seconds=0,max_wait_seconds=0,min_interval_seconds=0,ack_after_seconds=.005,max_burst=3)
        onebot=OneBot('ws://unused');sent=[];done=asyncio.Event()
        async def send(group,text):
            sent.append(text)
            if len(sent)==3:done.set()
        onebot.send_group_msg=send
        worker=GroupWorker(onebot,Cat(),cfg,123,logging.getLogger('test'))
        worker.start();worker.feed('test',1,'猫娘你好')
        try:
            await asyncio.wait_for(done.wait(),3)
            self.assertEqual(sent,['本喵想一下，等我几秒。','想好了！','原来是这样。'])
        finally:
            worker.stop();await asyncio.gather(worker._task,return_exceptions=True)


if __name__=='__main__':unittest.main()
