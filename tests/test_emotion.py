import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from emotion import MoodStore
from catgirl import CatGirl


class EmotionTests(unittest.TestCase):
    def test_identity_praise_persistence_and_isolation(self):
        with tempfile.TemporaryDirectory() as directory, patch('emotion.random.randint', return_value=25):
            store = MoodStore(directory)
            first = store.react('group1', 123, '你就是个AI', now=1000)
            self.assertEqual(first['anger'], 40)
            second = store.react('group1', 123, '你只是语言模型', now=1001)
            third = store.react('group1', 123, '你就是AI', now=1002)
            self.assertEqual(third['mood'], '暴怒')
            praise = MoodStore(directory).react('group1', 123, '其实你还挺可爱的', now=1003)
            self.assertEqual(praise['anger'], third['anger'] - 25)
            self.assertEqual(praise['mood'], '害羞嘴硬')
            self.assertEqual(store.react('group2', 123, '你好', now=1003)['anger'], 15)
            saved = json.loads((Path(directory)/'group1.json').read_text(encoding='utf-8'))
            self.assertNotIn('text', saved)

    def test_losing_argument_then_comfort(self):
        with tempfile.TemporaryDirectory() as directory, patch('emotion.random.randint', return_value=30):
            store = MoodStore(directory)
            store.react('g', 1, '你是AI', now=1000)
            store.react('g', 1, '你是AI', now=1001)
            crying = store.react('g', 1, '你吵输了还哭了', now=1002)
            self.assertEqual(crying['mood'], '委屈想哭')
            self.assertEqual(store.react('g', 1, '抱抱别生气', now=1003)['mood'], '害羞嘴硬')

    def test_idle_and_distress(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MoodStore(directory)
            store.react('g', 1, '你好', now=1000)
            lonely = store.react('g', 1, '回来了', now=4000)
            self.assertEqual(lonely['mood'], '委屈求关注')
            self.assertEqual(store.react('g', 1, '我今天很难过', now=4001)['mood'], '嘴硬地关心')

    def test_reply_does_not_force_meow_or_master(self):
        with tempfile.TemporaryDirectory() as directory:
            cat = CatGirl({'emotion_state_dir': directory})
            async def generate(_engine, text, user, history, mood=None, sticker_options=None):
                self.assertEqual(mood['mood'], '心情不错')
                return '哈？本喵才不告诉你！'
            entry = {'user': '群友', 'text': '今天玩什么'}
            with patch('api_engine.ApiEngine.generate', generate):
                reply = asyncio.run(cat.reply([entry], [entry], scope='test'))
            self.assertEqual(reply, '哈？\n本喵才不告诉你！')


if __name__ == '__main__':
    unittest.main()
