import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from import_stickers import build_catalog


class ImportTests(unittest.TestCase):
    def test_user_images_animation_dedup_and_bad_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);group=root/'委屈';group.mkdir()
            image=Image.new('RGB',(40,40),'blue');image.save(group/'猫猫.png')
            image.save(group/'重复.png')
            frames=[image,Image.new('RGB',(40,40),'red')]
            frames[0].save(root/'炸毛.gif',save_all=True,append_images=frames[1:],duration=100,loop=0)
            (root/'损坏.jpg').write_bytes(b'not an image')
            records,skipped=build_catalog(root)
            self.assertEqual(len(records),2);self.assertEqual(len(skipped),1)
            self.assertEqual(sum(r['animated'] for r in records),1)
            self.assertTrue(any('cry' in r['tags'] for r in records))
            self.assertTrue(all((root/r['file']).exists() for r in records))
            self.assertEqual(len(json.loads((root/'catalog.json').read_text(encoding='utf-8'))),2)


if __name__=='__main__':unittest.main()
