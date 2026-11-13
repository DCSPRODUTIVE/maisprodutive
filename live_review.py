"""Short sampled live clips from already open streams; never opens a new P2P session."""
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata

from google_ai import AIError
from camera_names import display_name


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))


def live_selector(text):
    value=normalized(text).strip()
    if value.startswith('/ao_vivo'):
        return value.partition(' ')[2].strip() or 'todas'
    if (('ao vivo' in value or 'agora' in value) and
            any(word in value for word in ('camera','cameras','veja','mostre','analise','olhe','ver '))):
        return 'todas' if re.search(r'\b(todas|todos)\b',value) else value
    return None


class LiveReview:
    def __init__(self,server,preview):
        self.server,self.preview=server,preview

    def sources(self,owner):
        rows={}
        for stream in self.server.stream_snapshot():
            if getattr(stream,'report_owner',None)==owner:
                rows[stream.device_id]={'id':stream.device_id,'name':display_name(getattr(stream,'report_name',None),stream.device_id),
                    'image':stream.image,'stamp':stream.last_frame,'active':not stream.stopped.is_set()}
        background=getattr(self.server,'background',None)
        if background:
            with background.lock:
                for device,name in getattr(background,'catalogues',{}).get(owner,{}).items():
                    rows.setdefault(device,{'id':device,'name':display_name(name,device),'active':False,'image':None,'stamp':None})
                for (entry_owner,device),entry in background.entries.items():
                    if entry_owner!=owner:continue
                    stream=entry.native
                    active=entry.window(time.monotonic()) and stream is not None and not stream.stopped.is_set()
                    rows[device]={'id':device,'name':display_name(entry.name,device),'active':active,
                                  'image':getattr(stream,'image',None) if active else entry.image,
                                  'stamp':getattr(stream,'last_frame',None) if active else entry.last_frame,
                                  'economy_paused':not entry.window(time.monotonic())}
        return rows

    def select(self,owner,selector):
        rows=list(self.sources(owner).values())[:12]
        if not rows:raise AIError('Não há câmeras em monitoramento nesta conta. Abra ou habilite as câmeras no painel.')
        if normalized(selector) in ('todas','todos','all'):
            return rows
        exact=[r for r in rows if normalized(r['name'])==normalized(selector)]
        matches=exact or [r for r in rows if normalized(r['name']) in normalized(selector)]
        if len(matches)!=1:
            names=', '.join(r['name'] for r in rows)
            raise AIError('Informe uma câmera sem ambiguidade: /ao_vivo NOME ou /ao_vivo todas. Disponíveis: '+names[:1000])
        return matches

    def capture(self,owner,selector,stopped,duration=6):
        selected=self.select(owner,selector)
        frames={r['id']:[] for r in selected};seen={};last_rows={}
        wall=time.time();start=time.monotonic();deadline=start+duration
        # Collect all cameras over one shared window, at most one image per second.
        while not stopped.is_set():
            now=time.monotonic();current=self.sources(owner)
            for row in selected:
                camera=row['id'];item=current.get(camera,row);last_rows[camera]=item
                stamp=item.get('stamp');image=item.get('image')
                if not item.get('active') or not image or stamp is None or now-stamp>3 or len(frames[camera])>=6:continue
                digest=hashlib.blake2s(image,digest_size=16).digest()
                if seen.get(camera)==digest:continue
                preview=self.preview(image)
                if preview:
                    frames[camera].append((now-start,preview));seen[camera]=digest
            if now>=deadline:break
            stopped.wait(min(1,max(0,deadline-time.monotonic())))
        results=[]
        for row in selected:
            samples=frames[row['id']];item=last_rows.get(row['id'],row)
            age=max(0,time.monotonic()-item['stamp']) if item.get('stamp') is not None else None
            result={'camera':row['id'],'nome':row['name'],'inicio_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(wall)),
                    'quadros_distintos':len(samples),'idade_ultimo_quadro_segundos':round(age,1) if age is not None else None}
            if item.get('economy_paused'):result['status']='pausa_economia'
            elif len(samples)<2:result['status']='sem_video_atual_confirmado'
            else:
                result['status']='trecho_atual_amostrado';result['duracao_segundos']=round(samples[-1][0]-samples[0][0],2)
                result['instantes_amostrados_segundos']=[round(stamp,2) for stamp,jpeg in samples]
                result['maior_intervalo_segundos']=round(max(samples[i+1][0]-samples[i][0] for i in range(len(samples)-1)),2)
                if result['maior_intervalo_segundos']>2 or age is None or age>3:result['status']='trecho_recente_parcial'
                result['amostragem']='até 1 quadro por segundo; sem áudio; somente período consultado'
                result['clip']=self.encode(samples)
                if not result['clip']:result['status']='conversao_indisponivel'
            results.append(result)
        return results

    @staticmethod
    def encode(samples):
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:return None
        from clips import ENCODERS
        if not ENCODERS.acquire(blocking=False):return None
        try:return LiveReview._encode(ffmpeg,samples)
        finally:ENCODERS.release()

    @staticmethod
    def _encode(ffmpeg,samples):
        with tempfile.TemporaryDirectory(prefix='dcs-ai-live-') as tmp:
            root=Path(tmp);entries=[]
            for index,(stamp,jpeg) in enumerate(samples):
                name=f'{index}.jpg';(root/name).write_bytes(jpeg)
                entries.append(f"file '{name}'\n")
                if index+1<len(samples):entries.append(f'duration {max(.05,samples[index+1][0]-stamp):.4f}\n')
            (root/'frames.txt').write_text(''.join(entries))
            output=root/'clip.mp4'
            try:
                subprocess.run([ffmpeg,'-v','error','-threads','1','-filter_threads','1','-f','concat','-safe','1','-i',str(root/'frames.txt'),
                    '-an','-vf','scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2,setsar=1',
                    '-fps_mode','vfr','-c:v','libx264','-preset','ultrafast','-crf','30','-threads','1','-pix_fmt','yuv420p','-movflags','+faststart',str(output)],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=12,check=True)
                return output.read_bytes() if output.stat().st_size<=2*1024*1024 else None
            except (OSError,subprocess.SubprocessError):return None
