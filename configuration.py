"""Portable defaults and validation. User configuration is never part of the repo."""
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import urlsplit

API_DEFAULTS = {'base_url':'', 'api_key':'', 'model':'', 'timeout':30.0,
                'max_tokens':400, 'temperature':0.9, 'json_mode':False, 'trust_env':True}

DEFAULT_CONFIG = {
    'onebot_url': 'ws://127.0.0.1:3001', 'access_token': '', 'self_id': 0,
    'groups': {'whitelist': [], 'blacklist': [], 'allow_all': False},
    'administration': {'admin_ids': [], 'allow_member_controls': False},
    'reply': {'trigger': 'mention_or_keyword', 'keywords': ['猫娘'], 'probability': 1.0,
              'min_interval_seconds': 3.0, 'debounce_seconds': 1.0, 'max_wait_seconds': 4.0,
              'context_size': 20, 'focus_recent': 2, 'max_burst': 4, 'ack_after_seconds': 6.0},
    'persona': {'name': '猫娘', 'call_user': '主人'},
    'privacy': {'log_message_content': False},
    'engine': {'profile_id': ''},
}


def deep_merge(base, override):
    result = deepcopy(base)
    for key, value in override.items():
        result[key] = deep_merge(result[key], value) if isinstance(result.get(key), dict) and isinstance(value, dict) else deepcopy(value)
    return result


def load_config(path):
    file = Path(path)
    if not file.exists():
        save_config(file, DEFAULT_CONFIG)
    data = json.loads(file.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('配置必须是 JSON 对象')
    return deep_merge(DEFAULT_CONFIG, data)


def save_config(path, config):
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_suffix('.tmp')
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(file)


def validate_api_settings(llm):
    endpoint = urlsplit(llm['base_url'])
    if endpoint.scheme not in ('http', 'https') or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        raise ValueError('请填写有效的模型 API 地址，不能在地址中嵌入凭据')
    if not str(llm['model']).strip():
        raise ValueError('请填写 API 平台提供的模型 ID')
    if not 1 <= float(llm['timeout']) <= 120 or not 1 <= int(llm['max_tokens']) <= 8192:
        raise ValueError('API 超时须为1～120秒，输出额度须为1～8192')
    if not isinstance(llm.get('api_key',''),str) or not 0<=float(llm.get('temperature',.9))<=2:
        raise ValueError('API Key须为文字，温度须为0～2')


def validate_config(config, require_groups=True, profile_store=None):
    uri = urlsplit(config['onebot_url'])
    if uri.scheme not in ('ws', 'wss') or not uri.hostname or uri.username or uri.password or uri.query or uri.fragment:
        raise ValueError('QQ 接入地址必须使用 ws:// 或 wss://')
    _ = uri.port
    from profiles import resolve_api_settings
    resolve_api_settings(config,profile_store)
    groups = config['groups']
    for key in ('whitelist', 'blacklist'):
        if not isinstance(groups[key], list) or any(type(g) is not int or g <= 0 for g in groups[key]):
            raise ValueError('群号列表必须包含正整数')
    if require_groups and not groups['whitelist'] and not groups.get('allow_all', False):
        raise ValueError('请先配置允许回复的群号；空白名单默认不回复任何群')
    reply = config['reply']
    if reply['trigger'] not in ('all', 'mention_or_keyword'):
        raise ValueError('触发方式须为 all 或 mention_or_keyword')
    if not 0 <= float(reply['probability']) <= 1:
        raise ValueError('回复概率必须在0～1之间')
    if not 1 <= int(reply['max_burst']) <= 4 or int(reply['context_size']) < 1:
        raise ValueError('每轮消息上限须为1～4，上下文数量须大于0')
    for key in ('min_interval_seconds', 'debounce_seconds', 'max_wait_seconds', 'ack_after_seconds'):
        if not 0 <= float(reply[key]) <= 300:
            raise ValueError(f'{key} 必须在0～300秒之间')
