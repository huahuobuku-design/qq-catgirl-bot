"""Persona, group mood and a provider-independent reply contract."""
import json
from pathlib import Path
import re
from api_engine import ApiEngine
from emotion import MoodStore
from stickers import StickerLibrary, split_short_messages

ROOT = Path(__file__).parent


def clip(text, n=40):
    text = str(text or '').strip()
    return text if len(text) <= n else text[:n] + '…'


def strip_cq(text):
    return re.sub(r'\[CQ:[^\]]*\]', '', str(text or '')).strip()


def is_noise(text):
    return not strip_cq(text).strip('。！？!?…~～.,， \t\n')


class CatGirl:
    def __init__(self, config, logger=None, transport=None):
        self.name = config.get('persona', {}).get('name', '猫娘')
        self.logger = logger
        self.llm = ApiEngine(config.get('llm', {}), transport=transport)
        self.moods = MoodStore(config.get('emotion_state_dir', ROOT/'data/mood'))
        self.stickers = StickerLibrary(config.get('sticker_dir'), config.get('sticker_state_dir', ROOT/'data/sticker_history'))
        self.reply_stickers = {}

    def _accept_reply(self, raw, scope, options):
        self.reply_stickers.pop(str(scope), None)
        raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.I)
        try:
            value = json.loads(raw)
        except ValueError:
            value = None
        if isinstance(value, dict) and isinstance(value.get('messages'), list):
            messages = [strip_cq(m) for m in value['messages'] if isinstance(m, str)]
            if value.get('sticker_id') in {r['id'] for r in options}:
                self.reply_stickers[str(scope)] = value['sticker_id']
        elif value is not None or raw.startswith(('{', '[')):
            raise ValueError('API 回复格式有误，messages 必须是文字列表')
        else:
            messages = [strip_cq(raw)]
        bubbles = split_short_messages(messages)
        if not bubbles:
            raise ValueError('API 回复为空')
        return '\n'.join(bubbles)

    async def reply(self, history, focus, scope='local'):
        focus = focus or history[-1:]
        if not focus:
            return ''
        last = focus[-1]
        text, user = str(last.get('text', '')), str(last.get('user', '群友'))
        mood = self.moods.react(scope, last.get('user_id', user), text)
        options = self.stickers.options(scope, mood, text)
        self.reply_stickers.pop(str(scope), None)
        raw = await self.llm.generate(text, user, history, mood, options)
        result = self._accept_reply(raw, scope, options)
        if self.logger:
            self.logger.info('API 回复生成完成，用时 %.1f 秒', self.llm.last_latency or 0)
        return result
