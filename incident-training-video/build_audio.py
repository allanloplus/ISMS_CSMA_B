#!/usr/bin/env python3
"""產生配音（edge-tts）、計算時間軸並合成整段音軌。

輸出：
  build/tts/*.mp3        每句配音（依內容雜湊快取）
  build/timeline.json    播放器／錄製用時間軸
  build/narration.wav    整段音軌（含音效）
"""
import asyncio, hashlib, json, os, subprocess, sys

import numpy as np

# 代理環境需使用指定 CA（若存在）
CA = '/root/.ccr/ca-bundle.crt'
if os.path.exists(CA):
    import certifi
    certifi.where = lambda: CA
import edge_tts  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, 'build')
TTS = os.path.join(BUILD, 'tts')
SR = 24000

VOICES = {
    'A': dict(voice='zh-TW-YunJheNeural', rate='+4%', pitch='+0Hz'),   # 講師 Allan：台灣男聲
    'R': dict(voice='zh-TW-HsiaoYuNeural', rate='+8%', pitch='+28Hz'),  # 助教 阿拉蕾：可愛女聲
}
GAP = 0.32          # 句與句之間
SCENE_IN = 0.9      # 每幕開頭留白（轉場）
SCENE_OUT = 1.0     # 每幕結尾留白
QUIZ_THINK = 3.0    # 測驗揭曉前的思考時間


def load_scenes():
    out = subprocess.check_output(['node', '-e', 'process.stdout.write(JSON.stringify(require("./scenes.js")))'], cwd=HERE)
    return json.loads(out)


def key(who, text):
    v = VOICES[who]
    return hashlib.sha1(json.dumps([v, text], ensure_ascii=False).encode()).hexdigest()[:16]


async def synth(sem, who, text, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    v = VOICES[who]
    async with sem:
        for attempt in range(5):
            try:
                await edge_tts.Communicate(text, v['voice'], rate=v['rate'], pitch=v['pitch']).save(path)
                if os.path.getsize(path) > 0:
                    return
            except Exception as e:  # 網路不穩重試
                print('retry', attempt, e, file=sys.stderr)
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError('TTS failed: ' + text)


def decode(path):
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', path, '-f', 's16le', '-ac', '1', '-ar', str(SR), '-'])
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    # 去除頭尾靜音，讓節奏更緊湊
    idx = np.where(np.abs(a) > 0.01)[0]
    if len(idx):
        a = a[max(0, idx[0] - int(0.05 * SR)): idx[-1] + int(0.12 * SR)]
    return a


def sfx_pop():
    t = np.arange(int(0.09 * SR)) / SR
    f = 900 + 1400 * t / t[-1]
    return 0.10 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 38)


def sfx_ding():
    t = np.arange(int(0.7 * SR)) / SR
    env = np.exp(-t * 5)
    return 0.11 * env * (np.sin(2 * np.pi * 1318.5 * t) + 0.6 * np.sin(2 * np.pi * 1975.5 * t))


def sfx_whoosh():
    rng = np.random.default_rng(1)
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    # 簡易低通
    k = 24
    noise = np.convolve(noise, np.ones(k) / k, mode='same')
    env = np.sin(np.pi * t / t[-1]) ** 2
    return 0.05 * noise * env


async def main():
    os.makedirs(TTS, exist_ok=True)
    scenes = load_scenes()
    sem = asyncio.Semaphore(4)
    jobs = []
    for sc in scenes:
        for ln in sc['lines']:
            text = ln.get('say') or ln['t']
            ln['_mp3'] = os.path.join(TTS, key(ln['s'], text) + '.mp3')
            jobs.append(synth(sem, ln['s'], text, ln['_mp3']))
    await asyncio.gather(*jobs)

    clips = []   # (start_sec, samples)
    t = 0.0
    tl = []
    for si, sc in enumerate(scenes):
        s0 = t
        clips.append((s0, sfx_whoosh()))
        t += SCENE_IN + (0.4 if si == 0 else 0)
        lines = []
        for ln in sc['lines']:
            if ln.get('reveal') and not any('三、二、一' in x['t'] for x in sc['lines']):
                t += QUIZ_THINK
            elif ln.get('reveal'):
                t += 0.6
            a = decode(ln['_mp3'])
            d = len(a) / SR
            clips.append((t, a))
            if ln.get('reveal') or ln.get('badge'):
                clips.append((t, sfx_ding()))
            if 'show' in ln:
                clips.append((t, sfx_pop()))
            item = {k: v for k, v in ln.items() if not k.startswith('_')}
            item.update(start=round(t, 3), end=round(t + d, 3))
            lines.append(item)
            t += d + GAP
        t += SCENE_OUT - GAP
        sc_out = {k: v for k, v in sc.items() if k != 'lines'}
        sc_out.update(start=round(s0, 3), end=round(t, 3), lines=lines)
        tl.append(sc_out)

    total = t + 0.5
    mix = np.zeros(int(total * SR) + SR, dtype=np.float32)
    for st, a in clips:
        i = int(st * SR)
        mix[i:i + len(a)] += a[: len(mix) - i]
    mix = np.clip(mix, -1, 1)
    wav = os.path.join(BUILD, 'narration.wav')
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 's16le', '-ar', str(SR), '-ac', '1', '-i', '-', wav], stdin=subprocess.PIPE)
    p.communicate((mix * 32767).astype(np.int16).tobytes())

    with open(os.path.join(BUILD, 'timeline.json'), 'w', encoding='utf-8') as f:
        json.dump({'duration': round(total, 3), 'scenes': tl}, f, ensure_ascii=False, indent=1)
    print(f'scenes={len(tl)} duration={total:.1f}s ({total/60:.1f} min)')


if __name__ == '__main__':
    asyncio.run(main())
