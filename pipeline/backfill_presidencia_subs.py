"""Pasada de auto-subs sobre el backlog de presidencia (19.6k videos).
Batch de 200, iterativo, checkpoint en presidencia_progress.json."""
import json, os, subprocess, time, sys
YTDLP = r'C:/Users/marti/uruguay-gov-audit/.venv/Scripts/yt-dlp.exe'
OUTDIR = r'C:/Users/marti/uruguay-gov-audit/data/transcripts/presidencia'
PROG = r'C:/Users/marti/uruguay-gov-audit/data/metadata/youtube/presidencia_progress.json'
os.makedirs(OUTDIR, exist_ok=True)

def run():
    wl = json.load(open(r'C:/Users/marti/uruguay-gov-audit/data/metadata/youtube/presidencia_worklist.json', encoding='utf-8'))
    prog = json.load(open(PROG, encoding='utf-8')) if os.path.exists(PROG) else {}
    for i, (vid, up) in enumerate(wl):
        if prog.get(vid): continue
        try:
            r = subprocess.run([YTDLP, '--skip-download', '--write-auto-subs', '--sub-langs', 'es',
                                '--convert-subs', 'vtt', '-o', os.path.join(OUTDIR, '%(id)s'),
                                f'https://www.youtube.com/watch?v={vid}'],
                               capture_output=True, text=True, timeout=120)
            prog[vid] = 'ok' if os.path.exists(os.path.join(OUTDIR, vid + '.es.vtt')) else ('no-subs' if r.returncode == 0 else 'fail:' + (r.stderr or '')[-60:])
        except Exception as e:
            prog[vid] = 'fail:' + str(e)[-80:]
        if i % 10 == 0:
            json.dump(prog, open(PROG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            n_ok = sum(1 for v in prog.values() if v == 'ok')
            print(i, '/', len(wl), 'ok:', n_ok, flush=True)
        time.sleep(2.5)
    json.dump(prog, open(PROG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('DONE', sum(1 for v in prog.values() if v == 'ok'), '/', len(prog))

if __name__ == '__main__':
    run()
