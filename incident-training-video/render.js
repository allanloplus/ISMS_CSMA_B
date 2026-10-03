#!/usr/bin/env node
// 以 Playwright 逐格擷取 player.html，交由 ffmpeg 合成 MP4。
// 用法：
//   node render.js stills 5 30 60          # 輸出指定秒數的截圖到 build/stills
//   node render.js video [--fps 24] [--workers 4]
//   COURSE_DIR=../incident-training-gov-b OUT_NAME=xxx.mp4 node render.js video   # 錄製其他課程
const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');                       // 以儲存庫根目錄提供網頁（課程間共用素材）
const COURSE = path.resolve(process.env.COURSE_DIR || __dirname);   // 課程資料夾
const COURSE_URL = '/' + path.relative(ROOT, COURSE).split(path.sep).map(encodeURIComponent).join('/');
const OUT_NAME = process.env.OUT_NAME || '資安事件通報與應變_教育訓練動畫.mp4';
const BUILD = path.join(COURSE, 'build');
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? Number(args[i + 1]) : d; };
const FPS = opt('--fps', 24);
const WORKERS = opt('--workers', 4);
const SCALE = 1.5; // 1280x720 → 1920x1080

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.png': 'image/png', '.ttf': 'font/ttf', '.m4a': 'audio/mp4', '.wav': 'audio/wav' };
function serve() {
  return new Promise(res => {
    const srv = http.createServer((req, rsp) => {
      const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
      if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { rsp.writeHead(404); return rsp.end(); }
      rsp.writeHead(200, { 'Content-Type': MIME[path.extname(p)] || 'application/octet-stream' });
      fs.createReadStream(p).pipe(rsp);
    }).listen(0, '127.0.0.1', () => res(srv));
  });
}

async function openPage(browser, port) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: SCALE });
  page.on('pageerror', e => console.error('pageerror', e));
  await page.goto(`http://127.0.0.1:${port}${COURSE_URL}/player.html?render`);
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 120000 });
  return page;
}

async function stills(browser, port, times) {
  const dir = path.join(BUILD, 'stills'); fs.mkdirSync(dir, { recursive: true });
  const page = await openPage(browser, port);
  for (const t of times) {
    await page.evaluate(t => window.renderAt(t), t);
    const f = path.join(dir, `t${String(t).padStart(6, '0')}.jpg`);
    await page.screenshot({ path: f, type: 'jpeg', quality: 85 });
    console.log(f);
  }
}

async function segment(browser, port, idx, f0, f1) {
  const out = path.join(BUILD, `seg_${idx}.mp4`);
  const page = await openPage(browser, port);
  // 確保所有圖片已解碼
  await page.evaluate(() => Promise.all([...document.images].map(i => i.decode().catch(() => {}))));
  const ff = spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-r', String(FPS), out], { stdio: ['pipe', 'inherit', 'inherit'] });
  const t0 = Date.now();
  for (let f = f0; f < f1; f++) {
    // 等瀏覽器實際完成繪製（兩個 animation frame）再擷取，避免漏畫圖層
    await page.evaluate(t => new Promise(res => { window.renderAt(t); requestAnimationFrame(() => requestAnimationFrame(res)); }), f / FPS);
    const buf = await page.screenshot({ type: 'jpeg', quality: 90 });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if ((f - f0) % 500 === 0) console.log(`[w${idx}] ${f - f0}/${f1 - f0} frames, ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
  await page.close();
  return out;
}

(async () => {
  const srv = await serve();
  const port = srv.address().port;
  const browser = await chromium.launch();
  try {
    if (args[0] === 'stills') {
      await stills(browser, port, args.slice(1).map(Number));
    } else {
      const tl = JSON.parse(fs.readFileSync(path.join(BUILD, 'timeline.json'), 'utf8'));
      const [r0, r1] = (process.env.RANGE || `0,${tl.duration}`).split(',').map(Number);   // 測試用：RANGE=秒,秒
      const f0 = Math.floor(r0 * FPS), total = Math.ceil(Math.min(r1, tl.duration) * FPS) - f0;
      const per = Math.ceil(total / WORKERS);
      const segs = await Promise.all([...Array(WORKERS).keys()].map(i => segment(browser, port, i, f0 + i * per, f0 + Math.min(total, (i + 1) * per))));
      const list = path.join(BUILD, 'segs.txt');
      fs.writeFileSync(list, segs.map(s => `file '${s}'`).join('\n'));
      const outMp4 = path.join(COURSE, OUT_NAME);
      await new Promise((res, rej) => {
        const ff = spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', list, ...(process.env.RANGE ? ['-ss', String(r0)] : []), '-i', path.join(BUILD, 'narration.wav'),
          '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k', '-shortest', '-movflags', '+faststart', outMp4], { stdio: 'inherit' });
        ff.on('close', c => c === 0 ? res() : rej(new Error('ffmpeg ' + c)));
      });
      console.log('done', outMp4);
    }
  } finally {
    await browser.close();
    srv.close();
  }
})();
