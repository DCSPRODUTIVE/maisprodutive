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
    int w, h, sy, su, sv, reason = 0; const void *y, *u, *v;
    memcpy(&w, av + 0x40, 4); memcpy(&h, av + 0x44, 4);
    memcpy(&y, av, 8); memcpy(&u, av + 0x10, 8); memcpy(&v, av + 0x20, 8);
    memcpy(&sy, av + 8, 4); memcpy(&su, av + 0x18, 4); memcpy(&sv, av + 0x28, 4);
    if (format != 0 && format != 1) reason = 17;
    else if (w < 16 || h < 16 || w > 4096 || h > 4096 || (w & 1) || (h & 1)) reason = 18;
    else if (!y || !u || !v) reason = 19;
    else if (sy < w*h || su < w*h/4 || sv < w*h/4) reason = 20;
    if (reason) {
        last_format = format; last_width = w; last_height = h;
        last_reason = reason; rejected++;
        /* Header changes and incomplete startup callbacks do not end capture. */
        InterlockedExchange(&writing, 0); return;
    }
    width = w; height = h;
    char header[120];
    int n = snprintf(header, sizeof(header), "YUV4MPEG2 W%d H%d F1:1 Ip A1:1 C420jpeg\nFRAME\n", w, h);
    if (!emit(header, n) || !emit(y, w*h) || !emit(u, w*h/4) || !emit(v, w*h/4)) {
        InterlockedExchange(&finished, -21); return;
    }
    InterlockedExchange(&finished, 1);
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
    if (argc==2 && (strcmp(argv[1],"--frame-selftest")==0 || strcmp(argv[1],"--frame-planar1-selftest")==0 || strcmp(argv[1],"--frame-incomplete-selftest")==0)) {
        unsigned char header[40]={0}, av[80]={0}, y[256], uv[64];
        const void *yp=y,*up=uv,*vp=uv; int w=16,h=16, sy=256, sc=64, pixel = strcmp(argv[1],"--frame-planar1-selftest")==0 ? 1 : 0;
        memset(y,100,sizeof(y)); memset(uv,128,sizeof(uv));
        memcpy(av,&yp,8);memcpy(av+16,&up,8);memcpy(av+32,&vp,8);memcpy(av+64,&w,4);memcpy(av+68,&h,4);
        memcpy(header+24,&pixel,4);memcpy(av+8,&sy,4);memcpy(av+24,&sc,4);memcpy(av+40,&sc,4);
        if (strcmp(argv[1],"--frame-incomplete-selftest")==0) {
            frame(&renderer,av); /* No init yet: must skip without emitting. */
            if (finished || rejected!=1) return 22;
        }
        init(&renderer,header);frame(&renderer,av);return finished==1?0:22;
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
    set_source(player,device,1,0,0);play(player);
    for(int i=0;i<250 && !InterlockedCompareExchange(&finished,0,0);i++)Sleep(100);
    if (finished==1) ExitProcess(0);
    if (finished<0) ExitProcess((UINT)-finished);
    if (rejected) {
        char metadata[128];
        int n=snprintf(metadata,sizeof(metadata),"MPVD1 %d %d %d %d\n",last_reason,last_format,last_width,last_height);
        emit(metadata,n);ExitProcess((UINT)last_reason);
    }
    ExitProcess(15);
}
