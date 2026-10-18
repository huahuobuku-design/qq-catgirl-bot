"""Local API records: create, select, read and delete; no update operation."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from types import MappingProxyType
from uuid import uuid4

from configuration import API_DEFAULTS, validate_api_settings

DEFAULT_DIRECTORY = Path(__file__).parent/'data/api_profiles'


@dataclass(frozen=True)
class ApiProfile:
    id: str
    name: str
    created_at: str
    settings: MappingProxyType


class ProfileStore:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else DEFAULT_DIRECTORY

    def _path(self, profile_id):
        if not isinstance(profile_id,str) or not re.fullmatch(r'[a-f0-9]{32}',profile_id):
            raise ValueError('API档案ID无效，请先新建并保存档案')
        return self.directory/(profile_id+'.json')

    @staticmethod
    def _digest(record):
        return hashlib.sha256(json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

    def create(self, name, settings):
        name=name.strip()
        if not 1<=len(name)<=60:raise ValueError('档案名称须为1～60个字符')
        if any(profile.name.casefold()==name.casefold() for profile in self.list()):
            raise ValueError('档案名称已存在，请换一个名称；现有档案不能修改')
        if any(key not in API_DEFAULTS for key in settings):raise ValueError('API档案包含不支持的字段')
        clean=dict(API_DEFAULTS,**settings)
        clean['base_url']=clean['base_url'].strip().rstrip('/')
        clean['model']=clean['model'].strip();clean['api_key']=clean['api_key'].strip()
        validate_api_settings(clean)
        record={'id':uuid4().hex,'name':name,'created_at':datetime.now(timezone.utc).isoformat(),'settings':clean}
        record['checksum']=self._digest(record)
        self.directory.mkdir(parents=True,exist_ok=True)
        # Exclusive creation prevents accidentally overwriting an existing record.
        fd=os.open(self._path(record['id']),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as file:json.dump(record,file,ensure_ascii=False,indent=2)
        return self.load(record['id'])

    def load(self, profile_id):
        try:
            record=json.loads(self._path(profile_id).read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise ValueError('API档案不存在或已删除，请新建或重新选择') from None
        except (OSError,ValueError):
            raise ValueError('API档案损坏或不可读取，请删除后重建') from None
        if not isinstance(record,dict) or not isinstance(record.get('settings'),dict):
            raise ValueError('API档案格式无效，请删除后重建')
        if set(record)!={'id','name','created_at','settings','checksum'} or set(record['settings'])!=set(API_DEFAULTS):
            raise ValueError('API档案字段无效，请删除后重建')
        checksum=record.pop('checksum',None)
        if record.get('id')!=profile_id or checksum!=self._digest(record):
            raise ValueError('API档案被外部修改或已损坏，请删除后重建')
        try:validate_api_settings(record['settings'])
        except (ValueError,TypeError,KeyError):
            raise ValueError('API档案参数无效，请删除后重建') from None
        return ApiProfile(record['id'],record['name'],record['created_at'],MappingProxyType(record['settings']))

    def list(self):
        result=[]
        for path in self.directory.glob('*.json'):
            try:result.append(self.load(path.stem))
            except (ValueError,KeyError,TypeError):continue
        return sorted(result,key=lambda p:(p.name.casefold(),p.id))

    def delete(self, profile_id):
        try:self._path(profile_id).unlink()
        except FileNotFoundError:raise ValueError('API档案已不存在') from None


def resolve_api_settings(config, store=None):
    store=store or ProfileStore()
    profile=store.load(config.get('engine',{}).get('profile_id',''))
    return dict(profile.settings,_profile_id=profile.id,_profiles_dir=str(store.directory.resolve()))


def main():
    import argparse
    import getpass
    parser=argparse.ArgumentParser(description='本地API档案：新建后只读，可删除但不可修改')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('create',help='交互式新建并保存，不把Key放入命令行历史')
    sub.add_parser('list',help='列出已保存档案，不显示Key')
    delete=sub.add_parser('delete',help='删除档案');delete.add_argument('id')
    args=parser.parse_args();store=ProfileStore()
    try:
        if args.command=='create':
            name=input('档案名称：').strip()
            settings={'base_url':input('API地址：').strip(),'model':input('模型ID：').strip(),
                      'api_key':getpass.getpass('API Key（本地接口可留空）：').strip()}
            profile=store.create(name,settings)
            print('已保存只读档案：'+profile.id+'；将其填入config.json的engine.profile_id即可使用。')
        elif args.command=='list':
            for profile in store.list():print(profile.id+'  '+profile.name+'  '+profile.settings['model'])
        elif input('删除后在用的群回复会停止。输入 DELETE 确认：')=='DELETE':
            store.delete(args.id);print('档案已删除')
    except (ValueError,OSError) as error:parser.exit(2,'操作失败：'+str(error)+'\n')


if __name__=='__main__':main()
