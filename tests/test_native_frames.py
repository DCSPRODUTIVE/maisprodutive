"""Compile actual callback/cadence code with host stubs; no camera or Wine needed."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'native/yoosee_snapshot.c'

@unittest.skipUnless(shutil.which('cc'),'C compiler required')
class NativeFrameTests(unittest.TestCase):
    def compile_run(self,source):
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'contract.c';file.write_text(source);exe=Path(directory)/'contract'
            result=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(file),'-o',str(exe)],capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr.decode())
            subprocess.run([str(exe)],check=True,timeout=5,capture_output=True)

    def test_fifteen_fps_source_is_sampled_at_ten_without_aliasing_down_to_seven(self):
        source=SOURCE.read_text();start=source.index('static int frame_due(');end=source.index('/* END portable frame cadence contract */',start)
        self.compile_run('#include <assert.h>\n'+source[start:end]+'''
int main(void) {
    unsigned long long next=0;int count=0;
    for(unsigned long long now=1000;now<2000;now+=67)count+=frame_due(now,&next);
    assert(count==10);
    assert(frame_due(10000,&next));assert(next==10100);
    assert(!frame_due(10001,&next));
    return 0;
}
''')

    def test_only_monotonic_in_range_camera_clock_frames_are_emitted(self):
        source=SOURCE.read_text();start=source.index('static void frame(void *self,');end=source.index('/* Minimal inline MSVC',start)
        cadence=source[source.index('static int frame_due('):source.index('/* END portable frame cadence contract */')]
        fixture=r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef long LONG;
typedef long long LONG64;
typedef unsigned long long ULONGLONG;
typedef unsigned DWORD;
static LONG writing,finished,frame_count,captured_frames;
static LONG64 archive_clock,captured_first,captured_last;
static int format=0,streaming,archive_mode=1,archive_frames=1,width,height,last_format,last_width,last_height,last_reason,rejected;
static ULONGLONG last_frame,next_frame;
static unsigned long long requested_begin=1800000000000ULL,requested_end=1800000005000ULL;
static unsigned char *chroma;
static size_t chroma_capacity,emitted;
static char header[120];
static LONG InterlockedCompareExchange(LONG *p,LONG value,LONG expected){LONG old=*p;if(old==expected)*p=value;return old;}
static LONG64 InterlockedCompareExchange64(LONG64 *p,LONG64 value,LONG64 expected){LONG64 old=*p;if(old==expected)*p=value;return old;}
static void InterlockedExchange(LONG *p,LONG value){*p=value;}
static void InterlockedExchange64(LONG64 *p,LONG64 value){*p=value;}
static void InterlockedIncrement(LONG *p){++*p;}
static ULONGLONG GetTickCount64(void){return 1000;}
static int emit(const void *data,DWORD size){if(!memcmp(data,"DCSYUV1",7))snprintf(header,sizeof(header),"%s",(const char *)data);emitted+=size;return 1;}
'''
        fixture+=cadence+source[start:end]+r'''
int main(void){
    unsigned char av[72]={0},y[256]={0},u[64]={0},v[64]={0};
    void *yp=y,*up=u,*vp=v;int sy=256,su=64,sv=64,w=16,h=16;
    memcpy(av,&yp,8);memcpy(av+16,&up,8);memcpy(av+32,&vp,8);
    memcpy(av+8,&sy,4);memcpy(av+24,&su,4);memcpy(av+40,&sv,4);
    memcpy(av+64,&w,4);memcpy(av+68,&h,4);
    archive_clock=(LONG64)requested_begin-1;frame(0,av);assert(!emitted);
    archive_clock=(LONG64)requested_begin+500;frame(0,av);
    assert(captured_frames==1);assert(captured_first==(LONG64)requested_begin+500);
    assert(strstr(header,"1800000000500 384\n"));size_t first=emitted;
    archive_clock=(LONG64)requested_begin+400;frame(0,av);assert(emitted==first);
    archive_clock=(LONG64)requested_begin+1500;frame(0,av);assert(captured_frames==2);
    archive_clock=(LONG64)requested_end;first=emitted;frame(0,av);assert(emitted==first);
    assert(captured_last==(LONG64)requested_begin+1500);
    return 0;
}
'''
        self.compile_run(fixture)
