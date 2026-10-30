"""Regression for the asynchronous SDK request-ID contract, without camera access."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('cc'), 'C compiler required')
class PlaybackContractTests(unittest.TestCase):
    def test_positive_request_ids_wait_for_callback_instead_of_failing(self):
        source=(Path(__file__).resolve().parents[1]/'native/yoosee_snapshot.c').read_text()
        start=source.index('static int playback_list_request(')
        end=source.index('/* END portable playback request contract */',start)
        # Compile the function used by the Windows adapter itself; no parallel
        # Python implementation of its success/error policy.
        contract=source[start:end]
        fixture=r'''
#include <assert.h>
#include <string.h>
static int result;
static int query(void *sdk,const char *device,unsigned long long begin,unsigned long long end) {
    assert(sdk==(void *)123);
    assert(strcmp(device,"owned-camera")==0);
    assert(begin==1799999880000ULL);
    assert(end==1800000120000ULL);
    return result;
}
'''
        fixture+=contract+r'''
int main(void) {
    int accepted[]={1,4096,2147483647};
    for (unsigned i=0;i<sizeof(accepted)/sizeof(*accepted);i++) {
        result=accepted[i];assert(playback_list_request((void *)123,"owned-camera",1800000000000ULL,1800000060000ULL,query)==0);
    }
    int rejected[]={0,-1,-100};
    for (unsigned i=0;i<sizeof(rejected)/sizeof(*rejected);i++) {
        result=rejected[i];assert(playback_list_request((void *)123,"owned-camera",1800000000000ULL,1800000060000ULL,query)==37);
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory);file=directory/'contract.c';file.write_text(fixture)
            exe=directory/'contract'
            subprocess.run([shutil.which('cc'),'-std=c11','-Wall','-Wextra','-Werror',str(file),'-o',str(exe)],check=True,timeout=15,capture_output=True)
            subprocess.run([str(exe)],check=True,timeout=5,capture_output=True)

    def test_sdk_microseconds_and_seek_target_use_correct_units_and_position(self):
        source=(Path(__file__).resolve().parents[1]/'native/yoosee_snapshot.c').read_text()
        start=source.index('static unsigned long long playback_clock_ms(')
        end=source.index('/* END portable playback clock contract */',start)
        fixture='#include <assert.h>\n'+source[start:end]+r'''
static void open_at(void *player,char *device,unsigned long long request,unsigned long long presentation) {
    assert(player==(void *)123);assert(device[0]=='c');
    assert(request==1800000000123ULL);assert(presentation==request);
}
static int seek(void *player,unsigned long long request,unsigned long long presentation,void *callback) {
    assert(player==(void *)123);assert(callback==(void *)456);
    assert(request==1800000000123ULL);assert(presentation==request);
    return 0;
}
int main(void) {
    assert(playback_clock_ms(1800000000123456ULL)==1800000000123ULL);
    assert(playback_clock_ms(1800000000123ULL)==1800000000123ULL);
    assert(playback_clock_ms(1800000000ULL)==0);
    assert(playback_clock_ms(0)==0);
    assert(playback_coverage(1800000000000ULL,1800000056762ULL,1800000000000ULL,1800000063960ULL)==1);
    assert(playback_coverage(1800000000000ULL,1800000063900ULL,1800000000000ULL,1800000063960ULL)==0);
    assert(playback_coverage(1700000000000ULL,1700000063960ULL,1800000000000ULL,1800000063960ULL)==2);
    playback_open_at((void *)123,"camera",1800000000123ULL,open_at);
    assert(playback_seek_start((void *)123,1800000000123ULL,(void *)456,seek)==0);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'clock.c';file.write_text(fixture);exe=Path(directory)/'clock'
            subprocess.run([shutil.which('cc'),'-std=c11','-Wall','-Wextra','-Werror',str(file),'-o',str(exe)],check=True,timeout=15,capture_output=True)
            subprocess.run([str(exe)],check=True,timeout=5,capture_output=True)

    def test_recorded_range_excludes_clock_callbacks_during_encoder_setup(self):
        source=(Path(__file__).resolve().parents[1]/'native/yoosee_snapshot.c').read_text()
        clock=source[source.index('static unsigned long long playback_clock_ms('):source.index('static void playback_open_at(')]
        callback=source[source.index('static void time_invoke('):source.index('static const void *time_type(')]
        fixture=r'''#include <assert.h>
typedef long long LONG64;
static long clock_callbacks,clock_unit,record_tracking;
static LONG64 archive_first_time,archive_last_time;
static void InterlockedIncrement(long *value) { ++*value; }
static void InterlockedExchange(long *value,long next) { *value=next; }
static void InterlockedExchange64(LONG64 *value,LONG64 next) { *value=next; }
static void InterlockedCompareExchange64(LONG64 *value,LONG64 next,LONG64 expected) { if(*value==expected)*value=next; }
'''+clock+callback+r'''
int main(void) {
    unsigned long long stamp=1800000000000000ULL;
    time_invoke(0,&stamp);
    assert(archive_first_time==0);assert(archive_last_time==1800000000000LL);
    stamp+=5800000ULL;time_invoke(0,&stamp);
    assert(archive_first_time==0);
    record_tracking=1;stamp+=100000ULL;time_invoke(0,&stamp);
    assert(archive_first_time==1800000005900LL);
    record_tracking=0;stamp+=200000ULL;time_invoke(0,&stamp);
    assert(archive_first_time==1800000005900LL);
    assert(clock_callbacks==4);assert(clock_unit==2);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'tracking.c';file.write_text(fixture);exe=Path(directory)/'tracking'
            subprocess.run([shutil.which('cc'),'-std=c11','-Wall','-Wextra','-Werror',str(file),'-o',str(exe)],check=True,timeout=15,capture_output=True)
            subprocess.run([str(exe)],check=True,timeout=5,capture_output=True)
