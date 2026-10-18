"""Index user-owned local images; never download or upload images."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).parent/'stickers'
CATEGORIES = {
    'angry': '炸毛|生气|暴怒|愤怒|嫌弃|哼|angry', 'cry':'委屈|哭|难过|伤心|cry',
    'shy':'害羞|贴贴|抱抱|爱心|比心|喜欢|可爱|shy', 'happy':'开心|哈哈|笑|快乐|happy',
    'smug':'得意|坏笑|嚣张|smug', 'confused':'疑问|问号|懵|疑惑|confused',
    'shocked':'震惊|惊讶|害怕|吓|shocked', 'sleepy':'困|睡|摆烂|累|sleepy',
    'care':'安慰|加油|关心|care', 'greeting':'招呼|你好|早安|再见|greeting',
    'food':'干饭|饿|吃饭|奶茶|food', 'playful':'调皮|围观|观察|玩|playful',
}


def build_catalog(directory=ROOT):
    root=Path(directory).resolve();root.mkdir(parents=True,exist_ok=True)
    records=[];skipped=[];seen=set()
    for file in sorted(root.rglob('*')):
        if not file.is_file() or file.suffix.lower() not in ('.png','.jpg','.jpeg','.gif','.webp'):continue
        if not file.resolve().is_relative_to(root) or file.stat().st_size>1_500_000:
            skipped.append(file.name);continue
        try:
            with Image.open(file) as image:
                if min(image.size)<20 or max(image.size)>2500:raise ValueError('dimensions')
                animated=getattr(image,'n_frames',1)>1;image.verify()
            digest=hashlib.sha256(file.read_bytes()).hexdigest()
        except (OSError,ValueError,UnidentifiedImageError,Image.DecompressionBombError):
            skipped.append(file.name);continue
        if digest in seen:continue
        seen.add(digest)
        relative=file.relative_to(root)
        tags=[tag for tag,pattern in CATEGORIES.items() if re.search(pattern,str(relative),re.I)] or ['playful']
        records.append({'id':'local_'+digest[:16],'title':file.stem[:80],'tags':tags,
                        'file':relative.as_posix(),'animated':animated,'sha256':digest})
    temporary=root/'catalog.tmp'
    temporary.write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temporary.replace(root/'catalog.json')
    return records,skipped


def main():
    parser=argparse.ArgumentParser(description='为用户自备的表情包建立本地索引')
    parser.add_argument('--directory',type=Path,default=ROOT)
    args=parser.parse_args();records,skipped=build_catalog(args.directory)
    print(f'已索引 {len(records)} 张图片，含 {sum(r["animated"] for r in records)} 张动图；跳过 {len(skipped)} 个无效、超大或重复文件。')


if __name__=='__main__':main()
