#!/usr/bin/env python3
"""產生網頁用的精簡字型（只保留實際用到的字），大幅縮短載入時間。

掃描儲存庫內所有頁面與腳本的文字，輸出：
  assets/fonts/Huninn-sub.woff2
  assets/fonts/NotoSansTC-900-sub.woff2
修改 scenes.js、quiz.html 或任何頁面文字後請重新執行。
完整 TTF 仍保留，供證書（使用者輸入的姓名等任意字）與影片錄製時使用。
"""
import glob, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FONTS = os.path.join(HERE, 'assets', 'fonts')

files = glob.glob(os.path.join(ROOT, '*.html'))
for d in glob.glob(os.path.join(ROOT, 'incident-training-*')):
    files += glob.glob(os.path.join(d, '*.html')) + glob.glob(os.path.join(d, 'scenes.js')) + glob.glob(os.path.join(d, 'build', 'timeline.json'))

chars = set()
for f in files:
    with open(f, encoding='utf-8') as fh:
        chars.update(fh.read())
# ASCII 與常用全形標點、數字
chars.update(chr(c) for c in range(0x20, 0x7f))
chars.update('，。、；：？！「」『』（）《》〈〉…—～・／｜＋－＝％＆＠＃０１２３４５６７８９　→➜✓✗○×')
chars = ''.join(sorted(c for c in chars if c.isprintable()))
txt = os.path.join(FONTS, '.subset-chars.txt')
with open(txt, 'w', encoding='utf-8') as fh:
    fh.write(chars)

for src, out in (('Huninn.ttf', 'Huninn-sub.woff2'), ('NotoSansTC-900.ttf', 'NotoSansTC-900-sub.woff2')):
    subprocess.check_call([sys.executable, '-m', 'fontTools.subset', os.path.join(FONTS, src),
                           f'--text-file={txt}', '--flavor=woff2', '--layout-features=*',
                           f'--output-file={os.path.join(FONTS, out)}'])
    print(out, os.path.getsize(os.path.join(FONTS, out)) // 1024, 'KB')
os.remove(txt)
print(len(chars), 'chars from', len(files), 'files')
