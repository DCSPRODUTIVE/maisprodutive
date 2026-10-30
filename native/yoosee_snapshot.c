/* Experimental x64 MSVC ABI adapter for the exact, locally imported DLL.
 * Recovered from the user-supplied 1.0.0.8 client; no vendor code included.
 * Credentials arrive on stdin, never command arguments. Only raw YUV exits.
 */
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <io.h>
#include <fcntl.h>

static HANDLE output;
static volatile LONG finished;
static volatile LONG writing;
static volatile LONG frame_count;
static int streaming;
static int archive_mode;
static int list_mode;
static unsigned char *chroma;
static size_t chroma_capacity;
static ULONGLONG last_frame, last_sent;
static int width, height, format = -1;
static int last_format = -1, last_width, last_height, last_reason, rejected;
static void *callbacks[4];
static struct { void **vtable; } renderer = { callbacks };

static int emit(const void *data, DWORD size) {
    DWORD written;
    return WriteFile(output, data, size, &written, NULL) && written == size;
}
static void *destroy(void *self, unsigned flags) { (void)flags; return self; }
static void init(void *self, const unsigned char *header) {
    (void)self;
    /* VideoRenderCase::init reads AVHeader+0x18; renderer dispatch 0/1 is planar. */
    memcpy(&format, header + 0x18, 4);
}
static void release(void *self) { (void)self; format = -1; }
static void frame(void *self, const unsigned char *av) {
    (void)self;
    if (InterlockedCompareExchange(&writing, 1, 0)) return;
    int w, h, sy, su, sv, reason = 0, planar = 0; const void *y, *u, *v;
    memcpy(&w, av + 0x40, 4); memcpy(&h, av + 0x44, 4);
    memcpy(&y, av, 8); memcpy(&u, av + 0x10, 8); memcpy(&v, av + 0x20, 8);
    memcpy(&sy, av + 8, 4); memcpy(&su, av + 0x18, 4); memcpy(&sv, av + 0x28, 4);
    if (format != 0 && format != 1 && format != 5) reason = 17;
    else if (w < 16 || h < 16 || w > 4096 || h > 4096 || (w & 1) || (h & 1)) reason = 18;
    else if (!y || !u || (format != 5 && !v)) reason = 19;
    else {
        /* The H.265 decoder can return three planes despite header format 5.
         * Inspect validated buffers before selecting the semiplanar fallback. */
        planar = v && su >= w*h/4 && sv >= w*h/4;
        if (sy < w*h || (!planar && (format != 5 || su < w*h/2))) reason = 20;
    }
    if (reason) {
        last_format = format; last_width = w; last_height = h;
        last_reason = reason; rejected++;
        /* Header changes and incomplete startup callbacks do not end capture. */
        InterlockedExchange(&writing, 0); return;
    }
    ULONGLONG now = GetTickCount64();
    if (streaming && frame_count && (w != width || h != height)) {
        InterlockedExchange(&finished, -23); return;
    }
    last_frame = now;
    if (archive_mode) { InterlockedIncrement(&frame_count); InterlockedExchange(&writing,0); return; }
    if (streaming && frame_count && now - last_sent < 100) {
        InterlockedExchange(&writing, 0); return;
    }
    if (format == 5 && !planar) {
        /* Native Windows semiplanar NV12: Y followed by interleaved UV. */
        size_t plane = (size_t)w*h/4;
        if (chroma_capacity < plane*2) {
            unsigned char *next = realloc(chroma,plane*2);
            if (!next) { InterlockedExchange(&finished,-26); return; }
            chroma = next; chroma_capacity = plane*2;
        }
        const unsigned char *uv = u;
        for (size_t i=0;i<plane;i++) { chroma[i]=uv[i*2]; chroma[plane+i]=uv[i*2+1]; }
        u=chroma;v=chroma+plane;
    }
    width = w; height = h;
    char header[120];
    int n;
    if (!frame_count) n = snprintf(header, sizeof(header), "YUV4MPEG2 W%d H%d F%d:1 Ip A1:1 C420jpeg\nFRAME\n", w, h, streaming ? 10 : 1);
    else n = snprintf(header, sizeof(header), "FRAME\n");
    if (!emit(header, n) || !emit(y, w*h) || !emit(u, w*h/4) || !emit(v, w*h/4)) {
        InterlockedExchange(&finished, -21); return;
    }
    last_sent = now;
    InterlockedIncrement(&frame_count);
    if (streaming) InterlockedExchange(&writing, 0);
    else InterlockedExchange(&finished, 1);
}

/* Minimal inline MSVC function<void(uint64_t)> for verified playback timestamps.
 * Vtable layout comes from _Func_base: copy, move, invoke, type, delete, target. */
static volatile LONG64 archive_first_time, archive_last_time;
static void *time_vtable[6];
static void *time_copy(void *self, void *destination) { (void)self; *(void ***)destination=time_vtable; return destination; }
/* BEGIN portable playback clock contract
 * Windows client's time listener divides the decoded PTS by 1,000,000 before
 * QDateTime::setTime_t (0x14011a8f5). List/seek use epoch milliseconds. */
static unsigned long long playback_clock_ms(unsigned long long stamp) {
    if (stamp>1000000000000000ULL && stamp<5000000000000000ULL) return stamp/1000ULL;
    if (stamp>1000000000000ULL && stamp<5000000000000ULL) return stamp;
    return 0;
}
static int playback_seek_start(void *player,unsigned long long target,void *callback,
    int (*seek)(void *,unsigned long long,unsigned long long,void *)) {
    /* Seek parameters are request position and presentation position, not end.
     * The PC's initial seek assigns the same epoch-ms value to both. */
    return seek(player,target,target,callback);
}
/* END portable playback clock contract */
static void time_invoke(void *self, const unsigned long long *stamp) {
    (void)self;
    unsigned long long milliseconds=playback_clock_ms(*stamp);
    if (milliseconds) {
        InterlockedCompareExchange64(&archive_first_time,(LONG64)milliseconds,0);
        InterlockedExchange64(&archive_last_time,(LONG64)milliseconds);
    }
}
static const void *time_type(void *self) { (void)self; return NULL; }
static void time_delete(void *self, unsigned char heap) { (void)self; (void)heap; }
static void *time_target(void *self) { return self; }
static void make_time_callback(unsigned char *storage) {
    memset(storage,0,64);
    time_vtable[0]=(void *)time_copy;time_vtable[1]=(void *)time_copy;
    time_vtable[2]=(void *)time_invoke;time_vtable[3]=(void *)time_type;
    time_vtable[4]=(void *)time_delete;time_vtable[5]=(void *)time_target;
    *(void ***)storage=time_vtable;
    *(void **)(storage+56)=storage;
}

/* PLaybackMessage: MSVC string (32 bytes), vector of 48-byte records.
 * Each record begins with uint64 start/end, followed by a 32-byte string. */
typedef struct { unsigned long long begin,end; } RecordRange;
static RecordRange record_ranges[512];
static unsigned record_count;
static volatile LONG list_received, list_callback_seen;
static ULONGLONG list_last;
static CRITICAL_SECTION list_lock;
static char query_device[128];
static void *list_vtable[6];
static void *list_copy(void *self,void *destination) { (void)self;*(void ***)destination=list_vtable;return destination; }
static void list_invoke(void *self,const int *kind,const unsigned char **message) {
    (void)self;(void)kind;
    InterlockedExchange(&list_callback_seen,1);
    if (!message) return;
    const unsigned char *m=*message;if (!m) return;
    size_t length,capacity;memcpy(&length,m+16,8);memcpy(&capacity,m+24,8);
    if (length!=strlen(query_device) || length>127) return;
    const char *device=(const char *)m;if (capacity>=16) memcpy(&device,m,8);
    if (!device || memcmp(device,query_device,length)) return;
    const unsigned char *first,*last;memcpy(&first,m+32,8);memcpy(&last,m+40,8);
    uintptr_t lo=(uintptr_t)first,hi=(uintptr_t)last;
    if (hi<lo || (hi-lo)%48 || hi-lo>48*4096) return;
    EnterCriticalSection(&list_lock);
    for (uintptr_t at=lo;at<hi && record_count<512;at+=48) {
        RecordRange range;memcpy(&range,(const void *)at,16);
        if (range.begin<1000000000000ULL || range.end<=range.begin || range.end>5000000000000ULL || range.end-range.begin>172800000ULL) continue;
        int duplicate=0;for (unsigned n=0;n<record_count;n++) if (record_ranges[n].begin==range.begin && record_ranges[n].end==range.end) duplicate=1;
        if (!duplicate) record_ranges[record_count++]=range;
    }
    list_last=GetTickCount64();InterlockedExchange(&list_received,1);
    LeaveCriticalSection(&list_lock);
}
/* BEGIN portable playback request contract
 * Unlike Register/seek, getPlaybackList returns a positive asynchronous request
 * identifier. SDK 0x32190 registers this identifier after send (0x32271); send
 * 0x607d0 returns a generated 31-bit ID. Zero/negative cannot track a request. */
static int playback_list_request(void *sdk,const char *device,unsigned long long begin,unsigned long long end,
    int (*query)(void *,const char *,unsigned long long,unsigned long long)) {
    int request=query(sdk,device,begin>3600000ULL?begin-3600000ULL:begin,end+60000ULL);
    return request>0 ? 0 : 37;
}
/* END portable playback request contract */
static void make_list_callback(unsigned char *storage) {
    memset(storage,0,64);list_vtable[0]=(void *)list_copy;list_vtable[1]=(void *)list_copy;
    list_vtable[2]=(void *)list_invoke;list_vtable[3]=(void *)time_type;
    list_vtable[4]=(void *)time_delete;list_vtable[5]=(void *)time_target;
    *(void ***)storage=list_vtable;*(void **)(storage+56)=storage;
}

typedef struct { union { char small[16]; void *ptr; } data; size_t size, capacity; } MsvcString;
static MsvcString make_string(const char *value, void *(*alloc)(size_t)) {
    MsvcString s; memset(&s, 0, sizeof(s)); s.size = strlen(value); s.capacity = 15;
    if (s.size < 16) memcpy(s.data.small, value, s.size+1);
    else { s.capacity=s.size; s.data.ptr=alloc(s.size+1); if (!s.data.ptr) ExitProcess(12); memcpy(s.data.ptr,value,s.size+1); }
    return s;
}
static void *symbol(HMODULE dll, const char *name) {
    void *p=(void *)GetProcAddress(dll,name); if (!p) ExitProcess(11); return p;
}
static int line(char *dest, size_t size) {
    if (!fgets(dest,(int)size,stdin)) return 0;
    size_t n=strcspn(dest,"\r\n"); if (!dest[n]) return 0; dest[n]=0; return n>0;
}
int main(int argc, char **argv) {
    SetErrorMode(SEM_FAILCRITICALERRORS|SEM_NOGPFAULTERRORBOX);
    if (sizeof(void *)!=8) return 10;
    /* Keep a private output handle; suppress all vendor stdout/stderr. */
    if (!DuplicateHandle(GetCurrentProcess(),GetStdHandle(STD_OUTPUT_HANDLE),GetCurrentProcess(),&output,0,FALSE,DUPLICATE_SAME_ACCESS)) return 10;
    freopen("NUL","w",stdout); freopen("NUL","w",stderr);
    SetStdHandle(STD_OUTPUT_HANDLE,GetStdHandle(STD_ERROR_HANDLE));
    callbacks[0]=(void *)destroy; callbacks[1]=(void *)init; callbacks[2]=(void *)frame; callbacks[3]=(void *)release;
    if (argc==2 && (strcmp(argv[1],"--frame-selftest")==0 || strcmp(argv[1],"--frame-planar1-selftest")==0 || strcmp(argv[1],"--frame-incomplete-selftest")==0 || strcmp(argv[1],"--stream-selftest")==0 || strcmp(argv[1],"--frame-nv12-selftest")==0 || strcmp(argv[1],"--frame-h265-planar-selftest")==0)) {
        unsigned char header[40]={0}, av[80]={0}, y[256], uv[64], nv12[128];
        const void *yp=y,*up=uv,*vp=uv; int w=16,h=16, sy=256, sc=64, pixel = strcmp(argv[1],"--frame-planar1-selftest")==0 ? 1 : 0;
        memset(y,100,sizeof(y)); memset(uv,128,sizeof(uv));
        memcpy(av,&yp,8);memcpy(av+16,&up,8);memcpy(av+32,&vp,8);memcpy(av+64,&w,4);memcpy(av+68,&h,4);
        if (strcmp(argv[1],"--frame-nv12-selftest")==0) {
            pixel=5;sc=128;vp=NULL;
            for (int i=0;i<64;i++) { nv12[i*2]=90;nv12[i*2+1]=180; }
            up=nv12;memcpy(av+16,&up,8);memcpy(av+32,&vp,8);
        }
        if (strcmp(argv[1],"--frame-h265-planar-selftest")==0) pixel=5;
        memcpy(header+24,&pixel,4);memcpy(av+8,&sy,4);memcpy(av+24,&sc,4);memcpy(av+40,&sc,4);
        if (strcmp(argv[1],"--frame-incomplete-selftest")==0) {
            frame(&renderer,av); /* No init yet: must skip without emitting. */
            if (finished || rejected!=1) return 22;
        }
        streaming = strcmp(argv[1],"--stream-selftest")==0;
        init(&renderer,header);
        if (streaming) {
            for (int i=0;i<6;i++) { memset(y,30+i*30,sizeof(y));frame(&renderer,av);Sleep(220); }
            return frame_count==6 ? 0 : 22;
        }
        frame(&renderer,av);return finished==1?0:22;
    }
    HMODULE dll=LoadLibraryExA("IotVideoSDK.dll",NULL,LOAD_LIBRARY_SEARCH_APPLICATION_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!dll) return 11;
    void *(*get_instance)(void)=symbol(dll,"?getInstance@IoTVideoSdk@@SAPEAV1@XZ");
    void (*construct)(void *)=symbol(dll,"??0IoTVideoPlayer@@QEAA@XZ");
    void (*set_render)(void *,void *)=symbol(dll,"?setVideoRender@IoTVideoPlayer@@QEAAXPEAVVideoRender@@@Z");
    void (*set_source)(void *,char *,int,int,unsigned short)=symbol(dll,"?setDataResource@IoTVideoPlayer@@QEAAXPEADW4CONNECT_TYPE@@W4DEFINITION@@G@Z");
    void (*play)(void *)=symbol(dll,"?play@IoTVideoPlayer@@QEAAXXZ");
    if (argc==2 && strcmp(argv[1],"--sdk-selftest")==0) {
        void *player=calloc(1,16);construct(player);set_render(player,&renderer);ExitProcess(0);
    }
    int definition = 0;
    streaming = argc==2 && (strcmp(argv[1],"--stream")==0 || strcmp(argv[1],"--stream-hd")==0 || strcmp(argv[1],"--stream-fhd")==0);
    if (streaming && strcmp(argv[1],"--stream-hd")==0) definition=1;
    if (streaming && strcmp(argv[1],"--stream-fhd")==0) definition=2;
    archive_mode = argc==2 && strcmp(argv[1],"--archive")==0;
    list_mode = argc==2 && strcmp(argv[1],"--list")==0;
    char id[128],token[8192],device[128];
    if (!line(id,sizeof(id)) || !line(token,sizeof(token)) || !line(device,sizeof(device))) return 12;
    HMODULE crt=LoadLibraryA("ucrtbase.dll"); if (!crt) return 11;
    void *(*alloc)(size_t)=symbol(crt,"malloc"); void (*free_mem)(void *)=symbol(crt,"free");
    int (*register_sdk)(void *,MsvcString *,MsvcString *)=symbol(dll,"?Register@IoTVideoSdk@@QEAAHV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV23@@Z");
    MsvcString access=make_string(id,alloc),secret=make_string(token,alloc);
    void *sdk=get_instance(); if (!sdk) return 13;
    int result=register_sdk(sdk,&access,&secret); /* access passed by value: callee destroys its buffer. */
    if(secret.capacity>=16)free_mem(secret.data.ptr);
    SecureZeroMemory(token,sizeof(token));SecureZeroMemory(&secret,sizeof(secret));
    if(result!=0)ExitProcess(14);
    Sleep(2000);
    void *player=calloc(1,16);construct(player);set_render(player,&renderer);
    if (archive_mode || list_mode) {
        /* MSVC std::function: 64-byte object; null implementation at +0x38.
         * The inspected SDK explicitly checks each empty callback before copying. */
        _Alignas(16) unsigned char callback1[64]={0},callback2[64]={0},callback3[64]={0};
        char begin_text[32],end_text[32],*tail;
        if (!line(begin_text,sizeof(begin_text)) || !line(end_text,sizeof(end_text))) ExitProcess(30);
        unsigned long long begin=strtoull(begin_text,&tail,10);if (*tail) ExitProcess(30);
        unsigned long long end=strtoull(end_text,&tail,10);if (*tail || end<=begin || end-begin>(list_mode?3600000ULL:125000ULL)) ExitProcess(30);
        InitializeCriticalSection(&list_lock);strcpy(query_device,device);
        _Alignas(16) unsigned char list_callback[64];make_list_callback(list_callback);
        void (*listen_list)(void *,void *)=symbol(dll,"?addPlaybackListListerner@IoTVideoSdk@@QEAAXV?$function@$$A6AXHPEAUPLaybackMessage@@@Z@std@@@Z");
        int (*query_list)(void *,const char *,unsigned long long,unsigned long long)=symbol(dll,"?getPlaybackList@IoTVideoSdk@@QEAAHPEBD_K1@Z");
        listen_list(sdk,list_callback);
        int query_status=playback_list_request(sdk,device,begin,end,query_list);
        if (query_status) ExitProcess(query_status);
        ULONGLONG queried=GetTickCount64();
        while (GetTickCount64()-queried<18000) {
            if (list_received && GetTickCount64()-list_last>1000) break;
            Sleep(50);
        }
        if (!list_received) ExitProcess(list_callback_seen?38:34);
        if (list_mode) {
            emit("SDLIST\n",7);
            EnterCriticalSection(&list_lock);
            for (unsigned i=0;i<record_count;i++) if (record_ranges[i].end>begin && record_ranges[i].begin<end) {
                char row[80];int bytes=snprintf(row,sizeof(row),"%llu %llu\n",record_ranges[i].begin,record_ranges[i].end);emit(row,bytes);
            }
            LeaveCriticalSection(&list_lock);ExitProcess(0);
        }
        unsigned long long file_begin=0,file_end=0;
        EnterCriticalSection(&list_lock);
        for (unsigned i=0;i<record_count;i++) {
            RecordRange r=record_ranges[i];
            if (r.begin<=begin && r.end>begin && (!file_begin || r.begin>file_begin)) {file_begin=r.begin;file_end=r.end;}
        }
        if (!file_begin) for (unsigned i=0;i<record_count;i++) {
            RecordRange r=record_ranges[i];if (r.begin>=begin && r.begin<=begin+5000 && (!file_begin || r.begin<file_begin)) {file_begin=r.begin;file_end=r.end;}
        }
        LeaveCriticalSection(&list_lock);
        if (!file_begin) ExitProcess(31);
        void (*set_playback)(void *,char *,unsigned long long,unsigned long long)=symbol(dll,"?setPlaybackDataResource@IoTVideoPlayer@@QEAAXPEAD_K1@Z");
        unsigned char (*start_record)(void *,MsvcString *,void *,void *,void *)=symbol(dll,"?startRecord@IoTVideoPlayer@@QEAA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@V?$function@$$A6AXXZ@3@V?$function@$$A6AX_K0@Z@3@V?$function@$$A6AXHV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@@Z@3@@Z");
        void (*stop_record)(void *)=symbol(dll,"?stopRecord@IoTVideoPlayer@@QEAAXXZ");
        unsigned char (*is_recording)(void *)=symbol(dll,"?isRecording@IoTVideoPlayer@@QEAA_NXZ");
        _Alignas(16) unsigned char time_callback[64];make_time_callback(time_callback);
        void (*set_time)(void *,void *)=symbol(dll,"?setTimeListener@IoTVideoPlayer@@QEAAXV?$function@$$A6AX_K@Z@std@@@Z");
        set_time(player,time_callback);
        set_playback(player,device,file_begin,file_end);play(player);
        ULONGLONG waiting=GetTickCount64();
        while (!frame_count && GetTickCount64()-waiting<25000) Sleep(50);
        if (!frame_count) ExitProcess(36);
        int (*seek)(void *,unsigned long long,unsigned long long,void *)=symbol(dll,"?seekPlaybackPosition@IoTVideoPlayer@@QEAAH_K0V?$function@$$A6AXE@Z@std@@@Z");
        InterlockedExchange64(&archive_last_time,0);
        if (playback_seek_start(player,begin,callback1,seek)!=0) ExitProcess(35);
        ULONGLONG seeking=GetTickCount64();
        while (GetTickCount64()-seeking<10000 && ((unsigned long long)archive_last_time<begin || (unsigned long long)archive_last_time>begin+5000)) Sleep(50);
        if ((unsigned long long)archive_last_time<begin || (unsigned long long)archive_last_time>begin+5000) ExitProcess(33);
        MsvcString filename=make_string("archive.mp4",alloc);
        InterlockedExchange64(&archive_first_time,0);
        if (!start_record(player,&filename,callback1,callback2,callback3)) ExitProcess(32);
        ULONGLONG started_record=GetTickCount64();
        while (GetTickCount64()-started_record<end-begin+8000) {
            if ((unsigned long long)archive_last_time>=end || GetTickCount64()-last_frame>8000) break;
            Sleep(100);
        }
        stop_record(player);
        ULONGLONG finishing=GetTickCount64();
        while (is_recording(player) && GetTickCount64()-finishing<5000) Sleep(50);
        Sleep(500);
        unsigned long long first=(unsigned long long)archive_first_time,last=(unsigned long long)archive_last_time;
        if (first<begin || first>begin+5000 || last+3000<end || last>end+5000) ExitProcess(33);
        char metadata[128];int count=snprintf(metadata,sizeof(metadata),"SDTIME %llu %llu\n",first,last);
        emit(metadata,count);ExitProcess(0);
    }
    set_source(player,device,1,definition,0);play(player);
    ULONGLONG started = GetTickCount64();
    for (;;) {
        LONG state = InterlockedCompareExchange(&finished,0,0);
        ULONGLONG now = GetTickCount64();
        if (state < 0 || (!streaming && state==1)) break;
        if (!frame_count && now-started>=25000) break;
        if (streaming && frame_count && now-last_frame>=8000) ExitProcess(24);
        /* Absolute bound even if the controlling process disappears. */
        if (streaming && now-started>=1200000) ExitProcess(25);
        Sleep(100);
    }
    if (finished==1) ExitProcess(0);
    if (finished<0) ExitProcess((UINT)-finished);
    if (rejected) {
        char metadata[128];
        int n=snprintf(metadata,sizeof(metadata),"MPVD1 %d %d %d %d\n",last_reason,last_format,last_width,last_height);
        emit(metadata,n);ExitProcess((UINT)last_reason);
    }
    ExitProcess(15);
}
