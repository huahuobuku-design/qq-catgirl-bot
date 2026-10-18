import asyncio
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stickers import StickerLibrary, split_short_messages
from catgirl import CatGirl
from bot import OneBot, GroupWorker, DEFAULT_CONFIG
import logging


class StickerTests(unittest.TestCase):
    def test_short_bubbles_keep_emphasis_and_caps(self):
        self.assertEqual(split_short_messages('哈？！\n不许说本喵笨！\n拿小鱼干来哄！'),
                         ['哈？！', '不许说本喵笨！', '拿小鱼干来哄！'])
        bubbles = split_short_messages('这是一句很长的回答，' * 30)
        self.assertLessEqual(len(bubbles), 3)
        self.assertTrue(all(len(b) <= 28 for b in bubbles))

    def _pack(self, root):
        (root/'a.gif').write_bytes(b'GIF89a')
        (root/'catalog.json').write_text(json.dumps([
            {'id': f'cat{i}', 'file':'a.gif', 'title':f'猫猫委屈{i}', 'tags':['cry'], 'animated':True}
            for i in range(25)] + [{'id':'escape', 'file':'../secret.gif','title':'bad','tags':[]}]),encoding='utf-8')

    def test_local_path_containment_cooldown_and_no_repeat(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'pack'; root.mkdir(); self._pack(root)
            library = StickerLibrary(root, Path(folder)/'state')
            self.assertNotIn('escape',library.records)
            options = library.options('g',{'mood':'委屈想哭'},'呜呜')
            self.assertEqual(len(options),24)
            selected = options[0]['id']; library.mark_sent('g',selected)
            self.assertEqual(library.options('g',{},'你好'),[])
            self.assertNotIn(selected,[r['id'] for r in library.options('g',{},'发表情包')])
            self.assertTrue(library.options('different_group',{},'你好'))
            self.assertEqual(library.options('g',{},'不要发表情包，只发文字'),[])
            self.assertTrue(all(r['animated'] for r in library.options('g',{},'发张GIF动图')))

    def test_structured_choice_is_validated_and_no_fixed_suffix(self):
        with tempfile.TemporaryDirectory() as folder:
            cat=CatGirl({'emotion_state_dir':folder,'sticker_state_dir':folder})
            response=json.dumps({'messages':['哈？！','不许笑！'], 'sticker_id':'unknown'})
            text=cat._accept_reply(response,'g',[{'id':'allowed'}])
            self.assertEqual(text,'哈？！\n不许笑！')
            self.assertNotIn('g',cat.reply_stickers)
            cat._accept_reply(response.replace('unknown','allowed'),'g',[{'id':'allowed'}])
            self.assertEqual(cat.reply_stickers['g'],'allowed')

    def test_image_is_real_onebot_segment(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as folder:
                file=Path(folder)/'a.gif';file.write_bytes(b'GIF89a-test')
                bot=OneBot('ws://127.0.0.1:3001')
                bot.call=AsyncMock(return_value={'status':'ok','retcode':0,'data':{'message_id':123}})
                self.assertEqual(await bot.send_group_image(99,str(file)),123)
                args=bot.call.call_args.args
                segment=args[1]['message'][0]
                self.assertEqual(segment['type'],'image')
                self.assertEqual(base64.b64decode(segment['data']['file'][9:]),b'GIF89a-test')
        asyncio.run(scenario())

    def test_worker_sends_separate_bubbles_then_image(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);self._pack(root)
                class Cat:
                    name='猫娘'
                    def __init__(self):
                        self.stickers=StickerLibrary(root,root/'state')
                        self.reply_stickers={}
                    async def reply(self,history,focus,scope='local'):
                        self.reply_stickers[scope]='cat1'
                        return '哈？！\n不许笑！\n哼！'
                bot=OneBot('ws://unused');cat=Cat();calls=[];done=asyncio.Event()
                async def send_text(g,text): calls.append(('text',text))
                async def send_image(g,path): calls.append(('image',path));done.set()
                bot.send_group_msg=send_text;bot.send_group_image=send_image
                cfg=json.loads(json.dumps(DEFAULT_CONFIG));cfg['reply'].update(debounce_seconds=0,max_wait_seconds=0,min_interval_seconds=0)
                worker=GroupWorker(bot,cat,cfg,99,logging.getLogger('test'))
                async def no_delay(seconds): return
                with patch('bot.asyncio.sleep',side_effect=no_delay):
                    worker.start();worker.feed('测试',1,'发个表情包')
                    await asyncio.wait_for(done.wait(),3)
                    worker.stop()
                self.assertEqual([c[0] for c in calls],['text','text','text','image'])
                self.assertEqual([c[1] for c in calls[:3]],['哈？！','不许笑！','哼！'])
                self.assertIn('cat1',cat.stickers._state('99')['recent'])
        asyncio.run(scenario())


if __name__=='__main__': unittest.main()
