"""Best-effort SD playback export; validated replacement only, never delete fallback."""
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import tempfile
import secrets
from types import SimpleNamespace
import threading
import time

import video

MAX_ARCHIVE_BYTES = 160 * 1024 * 1024
EXPORT_OVERHEAD = 90
LIST_BUDGET = 60
MAX_BOUNDARY_GAP_MS = 250
MAX_TOTAL_GAP_MS = 1000


class ArchiveFailure(RuntimeError):
    def __init__(self,reason,diagnostic=None):
        super().__init__(reason);self.diagnostic=diagnostic or {}


def native_failure(code,data):
    reasons={31:"no_recording",32:"recording_unavailable",33:"timestamp_unverified",34:"list_unavailable",
        35:"seek_unavailable",36:"playback_unavailable",37:"list_request_rejected",38:"list_response_unsupported",39:"list_incomplete"}
    diagnostic={}
    match=re.fullmatch(rb"SDFAIL1 ([0-9]{1,3}) ([0-9]) (-?[0-9]{1,3}) ([0-9]{1,4}) ([0-9]{1,10}) ([0-9]) (-?[0-9]{1,19}) ([0-9]{1,10}) ([0-9]{1,3})\n",data)
    if match and int(match[1])==code:
        keys=("stage","list_kind","records","clock_callbacks","clock_unit","clock_delta_ms","frames","frame_rejection")
        diagnostic=dict(zip(keys,(int(x) for x in match.groups()[1:])))
    return ArchiveFailure(reasons.get(code,"unavailable"),diagnostic)


def playback_segments(records,start,end):
    """Cover listed files; only tolerate bounded small boundary gaps."""
    cursor=round(start*1000);finish=round(end*1000);parts=[];gap=0
    rows=[(round(r["start"]*1000),round(r["end"]*1000)) for r in records]
    while cursor<finish:
        covering=[(a,b) for a,b in rows if a<=cursor<b]
        if not covering:
            following=[(a,b) for a,b in rows if cursor<a<=cursor+MAX_BOUNDARY_GAP_MS and b>cursor]
            if not following:raise RuntimeError("recording_gap")
            next_start=min(a for a,b in following);gap+=next_start-cursor
            if gap>MAX_TOTAL_GAP_MS:raise RuntimeError("recording_gap")
            cursor=next_start
            if cursor>=finish:break
            covering=[(a,b) for a,b in rows if a<=cursor<b]
        _,stop=max(covering,key=lambda row:(row[0],row[1]))
        stop=min(stop,finish);parts.append((cursor/1000,stop/1000));cursor=stop
        if len(parts)>8:raise RuntimeError("archive_fragmented")
    if not parts:raise RuntimeError("recording_gap")
    return parts


class CameraArchive:
    def __init__(self, store, slots):
        self.store,self.slots=store,slots
        self.queue=queue.Queue(maxsize=12)
        self.stopped=threading.Event()
        self.lock=threading.Lock();self.process=None
        self.failed={}
        self.jobs={}
        # Remove only stale private export directories from interrupted prior runs.
        for path in self.store.root.glob('sd-export-*'):
            try:
                if not path.is_symlink() and path.is_dir() and time.time()-path.stat().st_mtime>900:shutil.rmtree(path)
            except OSError:pass
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def enqueue(self, record_id, stream, start, end):
        if self.stopped.is_set() or not getattr(stream,'archive_account',None):return
        try:
            self.queue.put_nowait((record_id,stream,start,end,None,'automatic'))
        except queue.Full:self.status(record_id,'busy')

    def submit(self,owner,account,camera,start,end,action,monitor_until=float('inf')):
        stream=SimpleNamespace(report_owner=owner,device_id=camera['id'],report_name=camera['name'],
            report_detect=True,archive_account=account,monitor_until=monitor_until)
        key=secrets.token_urlsafe(18)
        record_id=None
        with self.lock:
            self.jobs={k:v for k,v in self.jobs.items() if time.monotonic()-v['created']<3600}
            if len(self.jobs)>=32:raise RuntimeError('busy')
            self.jobs[key]={'owner':owner,'created':time.monotonic(),'status':'queued','records':[],
                'record_id':None,'stream':stream,'partial':False,'diagnostic':{}}
        try:
            if action=='backup':
                import uuid
                record_id=self.store.video_add(owner,camera['id'],camera['name'],uuid.uuid4().hex+'.mp4')
                self.store.video_details(record_id,source='sd_requested',archive_status='queued')
                self.job_update(key,record_id=record_id)
            self.queue.put_nowait((record_id,stream,start,end,key,action))
        except queue.Full:
            if record_id:self.store.video_finish(record_id,'failed',0,'archive_busy')
            self.job_update(key,status='busy')
        except Exception:
            self.job_update(key,status='unavailable')
            if record_id:self.store.video_finish(record_id,'failed',0,'archive_unavailable')
            raise
        return key

    def job_update(self,key,**values):
        if key:
            with self.lock:
                if key in self.jobs:self.jobs[key].update(values)

    def job(self,owner,key):
        with self.lock:
            value=self.jobs.get(key)
            if not value or value['owner']!=owner:return None
            return {name:value[name] for name in ('status','records','record_id','partial','diagnostic')}

    def cancel(self,owner):
        with self.lock:
            for value in self.jobs.values():
                if value['owner']==owner:value['stream'].report_detect=False

    def configure_economy(self,owner,economy_ids,background):
        with self.lock:
            for value in self.jobs.values():
                stream=value['stream']
                if value['owner']==owner and value['status'] in ('queued','running') and stream.device_id in economy_ids:
                    stream.monitor_until=min(stream.monitor_until,background.deadline(owner,stream.device_id))

    def list_records(self,stream,start,end,directory):
        if not video.readiness()[0]:raise RuntimeError('adapter_update_required')
        account=stream.archive_account
        payload='\n'.join((account.access_id,account.access_token,stream.device_id,str(round(start*1000)),str(round(end*1000))))+'\n'
        if any(c in v for v in (account.access_id,account.access_token,stream.device_id) for c in '\r\n\0'):raise RuntimeError('unavailable')
        env=dict(os.environ,WINEDEBUG='-all',WINEDLLOVERRIDES='mscoree,mshtml=',WINEPREFIX=str(video.ROOT/'.local'/'wine-video'))
        # A bounded native listing can exceed a pipe's capacity; spool it to disk
        # so the child cannot deadlock while the parent waits for completion.
        output=open(Path(directory)/'listing.txt','w+b')
        try:
            child=self.launch([shutil.which('wine') or shutil.which('wine64'),str(video.NATIVE/'yoosee_snapshot.exe'),'--list'],
                cwd=directory,env=env,stdin=subprocess.PIPE,stdout=output)
        except Exception:
            output.close();raise
        try:
            child.stdin.write(payload.encode());child.stdin.close();deadline=time.monotonic()+28
            while child.poll() is None:
                if not self.allowed(stream):raise RuntimeError('economy_or_disabled')
                if time.monotonic()>deadline:raise ArchiveFailure('list_unavailable')
                self.stopped.wait(.2)
            output.seek(0);data=output.read(65536)
            if child.returncode:raise native_failure(child.returncode,data)
            header=data.splitlines()[0] if data else b''
            if header not in (b'SDLIST',b'SDLIST 0',b'SDLIST 1'):raise ArchiveFailure('list_response_unsupported')
            stream.archive_list_partial=header==b'SDLIST 1'
            records=[]
            for line in data.splitlines()[1:513]:
                match=re.fullmatch(rb'([0-9]{13}) ([0-9]{13})',line)
                if not match:raise ArchiveFailure('list_response_unsupported')
                begin,finish=(int(v)/1000 for v in match.groups())
                if begin<finish and finish>start and begin<end:records.append({'start':begin,'end':finish})
            return sorted(records,key=lambda row:row['start'])
        finally:
            self.kill(child);child.wait(timeout=5)
            if child.stdin and not child.stdin.closed:child.stdin.close()
            output.close()
            with self.lock:self.process=None

    def query_records(self,stream,start,end,directory):
        # Retry only a timeout or partial result, once; keep it bounded and obey
        # the same economy deadline instead of querying again for every part.
        partial=[]
        for attempt in range(2):
            try:
                records=self.list_records(stream,start,end,directory)
                if not getattr(stream,'archive_list_partial',False):return records
                partial.extend(records)
            except ArchiveFailure as error:
                if str(error) not in ('list_unavailable','list_incomplete') or attempt:raise
            if attempt==0:
                if not self.allowed(stream,30):raise RuntimeError('economy_or_disabled')
                self.stopped.wait(1)
        stream.archive_list_partial=True
        return [dict(start=a,end=b) for a,b in sorted({(r['start'],r['end']) for r in partial})]

    def status(self, record_id, status,diagnostic=None):
        with self.store.guard,self.store.connect() as db:
            db.execute('UPDATE videos SET archive_status=?,archive_diagnostic=? WHERE id=?',
                (status,json.dumps(diagnostic or {}),record_id))

    def allowed(self, stream, budget=0):
        return (not self.stopped.is_set() and getattr(stream,'report_detect',False)
                and time.monotonic()+budget<getattr(stream,'monitor_until',float('inf')))

    def launch(self,args,**kwargs):
        with self.lock:
            if self.stopped.is_set():raise RuntimeError('stopped')
            self.process=subprocess.Popen(args,start_new_session=True,stderr=subprocess.DEVNULL,**kwargs)
            return self.process

    def export(self,stream,start,end,directory):
        if not self.allowed(stream,end-start+EXPORT_OVERHEAD):return None
        deadline=time.monotonic()+end-start+EXPORT_OVERHEAD
        records=self.query_records(stream,start,end,directory)
        if not records:raise RuntimeError('no_recording')
        try:parts=playback_segments(records,start,end)
        except RuntimeError:
            if getattr(stream,'archive_list_partial',False):raise RuntimeError('list_incomplete')
            raise
        stream.archive_gap_seconds=round(max(0,end-start-sum(b-a for a,b in parts)),3)
        paths=[];pre_roll=0;coverage=[]
        stream.archive_partial=False
        stream.archive_actual_start=0;stream.archive_actual_end=0
        for index,(begin,finish) in enumerate(parts):
            if not self.allowed(stream) or time.monotonic()>=deadline:raise RuntimeError('bounded_export')
            folder=Path(directory)/f'piece-{index:02d}';folder.mkdir(mode=0o700)
            stream.archive_piece=None
            bounds=max((r for r in records if r['start']<=begin and r['end']>=finish),key=lambda r:r['start'])
            result=self.export_piece(stream,begin,finish,folder,overall_deadline=deadline,file_bounds=(bounds['start'],bounds['end']))
            if result is None:return None
            piece=getattr(stream,'archive_piece',None) or {'first':begin,'last':finish,'partial':False}
            if coverage and piece['first']-coverage[-1][1]>1:
                stream.archive_partial=True;break
            if index==0:pre_roll=result[1]
            paths.append(result[0]);coverage.append((piece['first'],piece['last']))
            stream.archive_actual_start=coverage[0][0];stream.archive_actual_end=coverage[-1][1]
            stream.archive_gap_seconds=round(max(0,coverage[-1][1]-coverage[0][0]-sum(b-a for a,b in coverage)),3)
            if piece['partial']:
                stream.archive_partial=True;break
            if sum(path.stat().st_size for path in paths)>MAX_ARCHIVE_BYTES:raise RuntimeError('bounded_export')
        if len(paths)==1:return paths[0],pre_roll
        # Numeric private paths only. Stream copy keeps the card's native FPS;
        # incompatible encodings are rejected rather than inventing missing frames.
        signatures=[]
        for path in paths:
            probe=subprocess.run([shutil.which('ffprobe'),'-v','error','-select_streams','v:0',
                '-show_entries','stream=codec_name,width,height','-of','json',str(path)],capture_output=True,timeout=10)
            data=json.loads(probe.stdout) if probe.returncode==0 else {}
            if not data.get('streams'):raise RuntimeError('invalid_video')
            info=data['streams'][0];signatures.append((info.get('codec_name'),info.get('width'),info.get('height')))
        if len(set(signatures))!=1:raise RuntimeError('invalid_video')
        manifest=Path(directory)/'pieces.txt'
        manifest.write_text(''.join(f"file 'piece-{i:02d}/archive.mp4'\n" for i in range(len(paths))))
        joined=Path(directory)/'archive.mp4'
        child=self.launch([shutil.which('ffmpeg'),'-v','error','-y','-f','concat','-safe','1','-i',str(manifest),
            '-map','0:v:0','-an','-c:v','copy','-movflags','+faststart',str(joined)],stdout=subprocess.DEVNULL)
        try:
            while child.poll() is None:
                if (not self.allowed(stream) or time.monotonic()>deadline or shutil.disk_usage(directory).free<256*1024*1024
                    or (joined.exists() and joined.stat().st_size>MAX_ARCHIVE_BYTES)):
                    raise RuntimeError('bounded_export')
                self.stopped.wait(.2)
            if child.returncode or not joined.exists():return None
            return joined,pre_roll
        finally:
            self.kill(child);child.wait(timeout=5)
            with self.lock:self.process=None

    def export_piece(self, stream, start, end, directory,overall_deadline=float("inf"),file_bounds=None):
        if not video.readiness()[0]:raise RuntimeError('adapter_update_required')
        if not self.allowed(stream,end-start+40):return None
        account=stream.archive_account
        payload='\n'.join((account.access_id,account.access_token,stream.device_id,str(round(start*1000)),str(round(end*1000))))+'\n'
        if any(c in v for v in (account.access_id,account.access_token,stream.device_id) for c in '\r\n\0'):return None
        env=dict(os.environ,WINEDEBUG='-all',WINEDLLOVERRIDES='mscoree,mshtml=',WINEPREFIX=str(video.ROOT/'.local'/'wine-video'))
        deadline=min(overall_deadline,time.monotonic()+end-start+60)
        if file_bounds is not None:payload+=''.join(str(round(value*1000))+'\n' for value in file_bounds)+str(max(1000,min(300000,round((deadline-time.monotonic()-2)*1000))))+'\n'
        process=self.launch([shutil.which('wine') or shutil.which('wine64'),str(video.NATIVE/'yoosee_snapshot.exe'),'--archive-known' if file_bounds is not None else '--archive'],
            cwd=directory,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
        try:
            process.stdin.write(payload.encode());process.stdin.close()
            output=Path(directory)/'archive.mp4'
            while process.poll() is None:
                if (not self.allowed(stream) or time.monotonic()>deadline or shutil.disk_usage(directory).free<256*1024*1024
                    or (output.exists() and output.stat().st_size>MAX_ARCHIVE_BYTES)):
                    raise RuntimeError('bounded_export')
                self.stopped.wait(.25)
            metadata=process.stdout.read(512)
            match=re.fullmatch(rb'(SDTIME|SDPART) ([0-9]{13}) ([0-9]{13})(?: ([1-3]))?\n',metadata)
            if process.returncode:raise native_failure(process.returncode,metadata)
            if not output.is_file() or output.stat().st_size>MAX_ARCHIVE_BYTES:return None
            if not match:raise RuntimeError('timestamp_unverified')
            partial=match[1]==b'SDPART'
            if (partial and match[4] is None) or (not partial and match[4] is not None):raise RuntimeError('timestamp_unverified')
            first,last=int(match[2])/1000,int(match[3])/1000
            if not start<=first<=start+5 or not first<last<=end+5 or (not partial and last<end-3):raise RuntimeError('timestamp_unverified')
            stream.archive_piece={'first':first,'last':last,'partial':partial}
            return output,round(max(0,min(5,start+5-first)),2)
        finally:
            self.kill(process);process.wait(timeout=5)
            if process.stdin and not process.stdin.closed:process.stdin.close()
            if process.stdout:process.stdout.close()
            with self.lock:self.process=None

    def replace(self, record_id, owner, path, desired_duration, pre_roll=0,allow_empty=False,gap_seconds=0,partial=False,confirmed_start=0,confirmed_end=0,source_override=None):
        # Decode only if the original codec needs browser compatibility. Never invent FPS.
        probe=subprocess.run([shutil.which('ffprobe'),'-v','error','-read_intervals','0%+1','-count_frames','-show_entries','stream=codec_type,codec_name,nb_read_frames:format=duration','-of','json',str(path)],capture_output=True,timeout=10)
        info=json.loads(probe.stdout) if probe.returncode==0 else {}
        duration=float(info.get('format',{}).get('duration',0))
        streams=[s for s in info.get('streams',[]) if s.get('codec_type')=='video']
        if (not streams or int(streams[0].get('nb_read_frames','0'))<1
            or duration<=0 or (not partial and duration<desired_duration-2) or duration>desired_duration+10):return False
        if confirmed_end>confirmed_start>0:
            expected=confirmed_end-confirmed_start-gap_seconds
            if abs(duration-expected)>max(2,expected*.03):return False
        target=self.store.video(owner,record_id)
        if target is None and not allow_empty:return False
        if shutil.disk_usage(path.parent).free<256*1024*1024:raise RuntimeError('disk_space')
        prepared=path.parent/'ready.mp4'
        codec=['-c:v','copy'] if streams[0]['codec_name']=='h264' else ['-c:v','libx264','-threads','1','-preset','veryfast','-crf','22']
        process=self.launch([shutil.which('ffmpeg'),'-v','error','-y','-threads','1','-i',str(path),'-map','0:v:0','-an',*codec,'-movflags','+faststart',str(prepared)],stdout=subprocess.DEVNULL)
        try:
            deadline=time.monotonic()+90
            while process.poll() is None:
                if self.stopped.wait(.25) or time.monotonic()>deadline or (prepared.exists() and prepared.stat().st_size>MAX_ARCHIVE_BYTES):raise RuntimeError('conversion')
                if shutil.disk_usage(path.parent).free<256*1024*1024:raise RuntimeError('disk_space')
            if process.returncode or not prepared.exists() or prepared.stat().st_size>MAX_ARCHIVE_BYTES:return False
            if shutil.disk_usage(path.parent).free<256*1024*1024:raise RuntimeError('disk_space')
            # Atomically switch the filename in SQLite. Existing viewers can finish the old file.
            import uuid
            filename=uuid.uuid4().hex+'.mp4'
            with self.store.guard,self.store.connect() as db:
                row=db.execute('SELECT filename FROM videos WHERE id=? AND owner=?',(record_id,owner)).fetchone()
                if not row:return False
                destination=self.store._video_path(filename)
                destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                os.chmod(prepared,0o600);prepared.replace(destination)
                status='partial' if partial or duration<desired_duration-1 else 'ready'
                try:db.execute("UPDATE videos SET filename=?,duration=?,status=?,reason='',source=?,archive_status='ready',archive_diagnostic='{}',sd_gap_seconds=?,pre_roll=?,archive_start=?,archive_end=? WHERE id=? AND owner=?",(filename,round(duration,2),status,source_override or ('sd_backup' if allow_empty else 'sd'),gap_seconds,0 if allow_empty and source_override!='sd_partial' else pre_roll,confirmed_start,confirmed_end,record_id,owner))
                except Exception:destination.unlink(missing_ok=True);raise
            if target:target.unlink(missing_ok=True)
            return True
        finally:
            self.kill(process);process.wait(timeout=5)
            with self.lock:self.process=None

    def run(self):
        while not self.stopped.is_set():
            try:record_id,stream,start,end,key,action=self.queue.get(timeout=.5)
            except queue.Empty:continue
            acquired=False
            try:
                camera=(stream.report_owner,stream.device_id)
                budget=LIST_BUDGET if action=='list' else end-start+EXPORT_OVERHEAD
                if not self.allowed(stream,budget):raise RuntimeError('economy_or_disabled')
                if action=='automatic' and time.monotonic()-self.failed.get(camera,-1e9)<600:raise RuntimeError('cooldown')
                acquired=self.slots.acquire(blocking=False)
                if not acquired:raise RuntimeError('busy')
                if record_id:self.status(record_id,'fetching')
                self.job_update(key,status='running')
                with tempfile.TemporaryDirectory(dir=self.store.root,prefix='sd-export-') as directory:
                    if action=='list':
                        records=self.query_records(stream,start,end,directory)
                        self.job_update(key,status='done',records=records,partial=getattr(stream,'archive_list_partial',False))
                    else:
                        result=self.export(stream,start,end,directory)
                        if not result or not self.allowed(stream):raise RuntimeError('unavailable')
                        partial=getattr(stream,'archive_partial',False)
                        saved_id=record_id
                        if partial and action=='automatic':
                            import uuid
                            saved_id=self.store.video_add(stream.report_owner,stream.device_id,stream.report_name,uuid.uuid4().hex+'.mp4')
                        saved=self.replace(saved_id,stream.report_owner,result[0],end-start,result[1],
                            allow_empty=action=='backup' or partial,gap_seconds=getattr(stream,'archive_gap_seconds',0),partial=partial,
                            confirmed_start=getattr(stream,'archive_actual_start',0),confirmed_end=getattr(stream,'archive_actual_end',0),
                            source_override='sd_partial' if partial and action=='automatic' else None)
                        if not saved:
                            if saved_id!=record_id:self.store.video_finish(saved_id,'failed',0,'invalid_video')
                            raise RuntimeError('unavailable')
                        if saved_id!=record_id:self.status(record_id,'partial_saved')
                        self.job_update(key,status='partial' if partial else 'done',record_id=saved_id)
                self.failed={k:v for k,v in self.failed.items() if time.monotonic()-v<600}
            except Exception as error:
                known=str(error) if isinstance(error,RuntimeError) else ''
                status=known if known in ('adapter_update_required','no_recording','timestamp_unverified','disk_space','list_unavailable',
                    'list_incomplete','recording_unavailable','recording_gap','archive_fragmented','seek_unavailable','playback_unavailable','list_request_rejected','list_response_unsupported','economy_or_disabled','cooldown','busy') else 'unavailable'
                try:
                    if record_id:self.status(record_id,status,getattr(error,'diagnostic',{}))
                    if action=='backup' and record_id:self.store.video_finish(record_id,'failed',0,'archive_'+status)
                    self.job_update(key,status=status,diagnostic=getattr(error,'diagnostic',{}))
                    if action=='automatic' and status not in ('economy_or_disabled','cooldown','busy'):
                        self.failed[(stream.report_owner,stream.device_id)]=time.monotonic()
                except Exception:pass
            finally:
                if acquired:self.slots.release()
                self.queue.task_done()

    @staticmethod
    def kill(process):
        if process.poll() is None:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass

    def close(self):
        self.stopped.set()
        with self.lock:
            if self.process:self.kill(self.process)
        self.thread.join(timeout=3)
        while True:
            try:self.queue.get_nowait();self.queue.task_done()
            except queue.Empty:break
