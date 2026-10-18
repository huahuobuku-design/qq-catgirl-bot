"""Local, indexed sticker choices. The model selects IDs, never file paths."""
from collections import deque
import json
from pathlib import Path
import random
import re
import time

ROOT = Path(__file__).parent
LABELS = {'angry': '炸毛生气', 'cry': '委屈哭哭', 'shy': '害羞贴贴', 'happy': '开心大笑',
          'smug': '得意坏笑', 'confused': '疑问懵圈', 'shocked': '震惊害怕',
          'sleepy': '困倦摆烂', 'care': '关心安慰', 'greeting': '打招呼', 'food': '馋猫干饭', 'playful': '围观调皮'}


def split_short_messages(text, limit=28, count=3):
    """Prefer semantic boundaries, then cap both bubble size and bubble count."""
    lines = text if isinstance(text, list) else [text]
    result = []
    for line in lines:
        line = re.sub(r'\[CQ:[^\]]*\]|\[\[sticker:[^\]]*\]\]', '', str(line)).strip()
        pieces = re.split(r'(?<=[。！？!?；;])(?=[^。！？!?；;])|\n+', line)
        for piece in pieces:
            piece = piece.strip()
            while len(piece) > limit:
                boundary = max(piece.rfind('，', 0, limit), piece.rfind('、', 0, limit),
                               piece.rfind(' ', 0, limit), piece.rfind('：', 0, limit))
                end = boundary + 1 if boundary >= 5 else limit
                result.append(piece[:end].strip())
                piece = piece[end:].strip()
            if piece:
                result.append(piece)
    if len(result) > count:
        result = result[:count]
        if result[-1][-1:] not in '。！？!?…':
            result[-1] = result[-1][:limit - 1] + '…'
    return result


class StickerLibrary:
    def __init__(self, directory=None, state_dir=None):
        self.directory = Path(directory) if directory else ROOT / 'stickers'
        self.state_dir = Path(state_dir) if state_dir else ROOT / 'sticker_state'
        self.records = {}
        self._mtime = None
        self.refresh()

    def refresh(self):
        manifest = self.directory / 'catalog.json'
        try:
            mtime = manifest.stat().st_mtime_ns
            if self._mtime == mtime:
                return
            records = json.loads(manifest.read_text(encoding='utf-8'))
            checked = {}
            root = self.directory.resolve()
            for record in records:
                file = (root / record['file']).resolve()
                if not file.is_relative_to(root) or file.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
                    continue
                if file.is_file() and file.stat().st_size <= 1_500_000:
                    checked[record['id']] = record
            self.records = checked
            self._mtime = mtime
        except (OSError, ValueError, KeyError, TypeError):
            self.records = {}

    def _state_path(self, scope):
        return self.state_dir / (re.sub(r'[^a-zA-Z0-9_-]', '_', str(scope))[:80] + '.json')

    def _state(self, scope):
        try:
            return json.loads(self._state_path(scope).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def options(self, scope, mood, text, now=None):
        self.refresh()
        if re.search(r'(别|不要|不用|停止).{0,5}(发图|发.{0,3}表情|发.{0,3}动图)|只.{0,2}(文字|发文字)', text):
            return []
        state = self._state(scope)
        now = time.time() if now is None else now
        requested = bool(re.search(r'表情包|斗图|发.{0,4}(张图|图片|动图|猫图)', text))
        if not requested and now - state.get('last_sent', 0) < 12:
            return []
        wanted = {
            '暴怒': ['angry', 'smug'], '有点炸毛': ['angry', 'playful'],
            '委屈想哭': ['cry'], '害羞嘴硬': ['shy'], '开心得意': ['happy', 'smug'],
            '委屈求关注': ['cry', 'shy'], '嘴硬地关心': ['care', 'shy'],
        }.get(mood.get('mood'), ['happy', 'playful', 'confused'])
        for tag, pattern in (('sleepy', '困|睡|晚安|累'), ('food', '吃|饿|饭|奶茶'),
                             ('greeting', '你好|早上好|早安|拜拜'), ('confused', '什么|怎么|为什么|不懂'),
                             ('shy', '可爱|抱抱|贴贴|喜欢|摸摸'), ('cry', '委屈|哭|难过')):
            if re.search(pattern, text):
                wanted.insert(0, tag)
        recent = set(state.get('recent', [])[-18:])
        candidates = [r for r in self.records.values() if r['id'] not in recent]
        if re.search(r'动图|gif', text, re.I):
            animated = [r for r in candidates if r.get('animated')]
            if animated:
                candidates = animated
        random.shuffle(candidates)
        candidates.sort(key=lambda r: sum((len(wanted) - i) for i, tag in enumerate(wanted) if tag in r['tags']), reverse=True)
        selected = candidates[:24]
        return [{'id': r['id'], 'meaning': r['title'],
                 'emotion': [LABELS.get(t, t) for t in r['tags']], 'animated': r.get('animated', False)} for r in selected]

    def get(self, sticker_id):
        record = self.records.get(sticker_id)
        return dict(record, path=str((self.directory / record['file']).resolve())) if record else None

    def mark_sent(self, scope, sticker_id):
        state = self._state(scope)
        recent = deque(state.get('recent', []), maxlen=18)
        recent.append(sticker_id)
        state = {'recent': list(recent), 'last_sent': time.time()}
        self.state_dir.mkdir(parents=True, exist_ok=True)
        path = self._state_path(scope)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
