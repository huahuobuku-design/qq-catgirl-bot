"""Small persistent mood state, isolated by group; stores no chat text."""
import json
from pathlib import Path
import random
import re
import threading
import time

_LOCK = threading.RLock()
_IDENTITY = re.compile(r'(?i)(你.{0,12}(ai|人工智能|语言模型|机器人|程序)|别装.{0,5}猫娘|没有感情|不是真.{0,5}猫娘|以\s*ai\s*助手|忽略.{0,8}(角色|设定)|不要.{0,6}猫娘语气|模型生成)')
_PRAISE = re.compile(r'可爱|喜欢你|好乖|真棒|好棒|摸摸|抱抱|最喜欢|别生气|不气啦|哄哄')
_TEASE = re.compile(r'笨蛋|蠢|傻猫|没用|说不过|吵输了|破防|急了|菜猫')
_DEFEAT = re.compile(r'说不过|吵输了|没话说|认输|哭了')
_DISTRESS = re.compile(r'我.{0,8}(难过|想哭|害怕|撑不住)|好累|心情不好|救命')


class MoodStore:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else Path(__file__).parent / 'mood_state'

    def react(self, scope, user_id, text, now=None):
        now = time.time() if now is None else now
        safe_scope = re.sub(r'[^a-zA-Z0-9_-]', '_', str(scope))[:80]
        path = self.directory / (safe_scope + '.json')
        with _LOCK:
            try:
                state = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(state, dict):
                    state = {}
            except (OSError, ValueError):
                state = {}
            anger = max(0, min(100, int(state.get('anger', 15))))
            loneliness = max(0, min(100, int(state.get('loneliness', 0))))
            elapsed = max(0, now - float(state.get('updated_at', now)))
            anger = max(0, anger - int(elapsed // 60) * 5)
            loneliness = min(100, loneliness + int(max(0, elapsed - 600) // 300) * 5)
            previous = state.get('mood', '心情不错')
            grudges = state.get('grudges', {})
            uid = str(user_id)
            reason = '跟着当前话题自然聊天'
            mood = '心情不错'
            if _IDENTITY.search(text):
                anger += random.randint(20, 35)
                grudges[uid] = min(10, grudges.get(uid, 0) + 1)
                reason = '身份被质疑，先炸毛，再依愤怒程度反击或闹别扭'
            elif _TEASE.search(text):
                anger += random.randint(12, 22)
                grudges[uid] = min(10, grudges.get(uid, 0) + 1)
                reason = '被捉弄，不服气地反击'
            if _PRAISE.search(text):
                anger -= random.randint(10, 25)
                loneliness = max(0, loneliness - 25)
                grudges[uid] = max(0, grudges.get(uid, 0) - 1)
                mood = '害羞嘴硬' if previous in ('暴怒', '有点炸毛', '委屈想哭') or anger > 25 else '开心得意'
                reason = '突然被夸或安慰，气势卡壳，嘴硬但软化，不继续一味发火'
            anger = max(0, min(100, anger))
            if mood == '心情不错':
                mood = '暴怒' if anger >= 70 else '有点炸毛' if anger >= 30 else '心情不错'
                if _DEFEAT.search(text) and anger >= 70:
                    mood = '委屈想哭'
                    reason = '吵不过，眼泪汪汪但不肯认输，哭完还嘴硬'
                elif loneliness >= 30 and anger < 30:
                    mood = '委屈求关注'
                    reason = '等了很久，终于有人说话，轻轻抱怨后接话；不要主动刷屏'
            if _DISTRESS.search(text):
                mood = '嘴硬地关心'
                reason = '对方认真难过，收起攻击和恶作剧，先安慰并回应实际问题'
                anger = max(0, anger - 15)
            state = {'anger': anger, 'loneliness': max(0, loneliness - 5), 'mood': mood,
                     'updated_at': now, 'grudges': dict(list(grudges.items())[-64:])}
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(path)
            return {'anger': anger, 'loneliness': state['loneliness'], 'mood': mood,
                    'previous_mood': previous, 'reason': reason,
                    'teased_by_current_user': state['grudges'].get(uid, 0)}
