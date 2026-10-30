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
    assert(begin==1799996400000ULL);
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
