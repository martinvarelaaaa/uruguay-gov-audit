
import json, os, subprocess, time, sys, glob
WL = json.load(open(r'C:/Users/marti/uruguay-gov-audit/data/metadata/youtube/autotranscript_worklist.json', encoding='utf-8'))
WL = [w for w in WL if w[0] in ('senado','diputados','parlamento')]
YTDLP = r'C:/Users/marti/uruguay-gov-audit/.venv/Scripts/yt-dlp.exe'
OUTBASE = r'C:/Users/marti/uruguay-gov-audit/data/transcripts'
done = json.load(open(r'C:/Users/marti/uruguay-gov-audit/data/metadata/youtube/autotranscript_progress.json','r',encoding='utf-8')) if os.path.exists(r'C:/Users/marti/uruguay-gov-audit/data/metadata/youtube/autotranscript_progress.json') else {}
for slug, vid, up, title in WL:
    if done.get(vid): continue
    outdir = os.path.join(OUTBASE, slug)
    os.makedirs(outdir, exist_ok=True)
    try:
        r = subprocess.run([YTDLP, '--skip-download', '--write-auto-subs', '--sub-langs', 'es', '--convert-subs', 'vtt',
                            '-o', os.path.join(outdir, '%(id)s'),
                            f'https://www.youtube.com/watch?v={vid}'],
                           capture_output=True, text=True, timeout=120)
        vtt = os.path.join(outdir, vid + '.es.vtt')
        if os.path.exists(vtt):
            done[vid] = 'ok'
        else:
            done[vid] = 'no-subs' if r.returncode == 0 else ('fail:' + (r.stderr or '')[-60:])
    except Exception as e:
        done[vid] = 'fail:' + str(e)[-80:]
    json.dump(done, open(r'C:/Users/marti/uruguay-gov-audit/data/metadata/youtube/autotranscript_progress.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
    n_done = sum(1 for v in done.values() if v=='ok')
    if n_done % 25 == 0: print(n_done, 'ok /', len(done), flush=True)
    time.sleep(3)
print('DONE ok:', sum(1 for v in done.values() if v=='ok'), 'total processed:', len(done))
