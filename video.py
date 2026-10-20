"""One-frame experimental native adapter. No account credentials are persisted."""
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import tempfile

from yoosee import IntegrationError

ROOT = Path(__file__).parent
NATIVE = ROOT / '.local' / 'video'
DLL_HASHES = {
    'IotVideoSDK.dll': 'e1a93b18fbac566f5350a5e9b6156839acca48fa0088689993301dec77be6053',
    'msvcp140.dll': '10ddff48d704c6007e4c2d53fb4856b5e5e79479503366236246a323aaa76e9d',
    'vcruntime140.dll': '8ee6b49830436ff3bec9ba89213395427b5535813930489f118721fd3d2d942c',
    'vcruntime140_1.dll': 'f8bc270449ca6bb6345e88be3632d465c0a7595197c7954357dc5066ed50ae44',
}


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def readiness():
    if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        return False, 'O adaptador experimental exige Linux x86_64.'
    if not (shutil.which('wine') or shutil.which('wine64')) or not shutil.which('ffmpeg'):
        return False, 'Prepare a captura no Terminal conforme o README: são necessários Wine, FFmpeg e o adaptador local.'
    try:
        manifest = json.loads((NATIVE / 'manifest.json').read_text())
        expected = DLL_HASHES | {'yoosee_snapshot.exe': manifest['bridge_sha256']}
        if manifest['source_sha256'] != checksum(ROOT / 'native' / 'yoosee_snapshot.c'):
            raise ValueError
        if any(checksum(NATIVE / name) != digest for name, digest in expected.items()):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        return False, 'Execute configure_video.py com o instalador 1.0.0.8 para preparar o adaptador de imagem.'
    return True, 'Adaptador preparado. Use Testar imagem em uma câmera para verificar a captura.'


def native_failure(code, raw=b''):
    reasons = {11: 'Não foi possível carregar a biblioteca local.',
               14: 'O SDK não aceitou o registro da sessão.',
               15: 'A conexão P2P não entregou um quadro em 25 segundos.',
               16: 'O adaptador anterior rejeitou os dados do quadro.',
               17: 'O SDK informou um formato de imagem ainda não suportado.',
               18: 'O quadro chegou com dimensões inválidas ou não suportadas.',
               19: 'O quadro chegou sem todos os planos de imagem.',
               20: 'Os buffers do quadro não têm os tamanhos esperados.',
               21: 'Não foi possível transferir o quadro do adaptador.',
               23: 'A resolução da câmera mudou durante a transmissão. Inicie novamente.',
               24: 'A câmera parou de entregar quadros por 15 segundos.',
               25: 'O limite de tempo da transmissão foi atingido. Inicie novamente.',
               26: 'Não foi possível reservar memória para converter a imagem.'}
    diagnostic = re.fullmatch(rb'MPVD1 (17|18|19|20) (-?[0-9]{1,11}) (-?[0-9]{1,11}) (-?[0-9]{1,11})\n', raw)
    details = ''
    if diagnostic and int(diagnostic[1]) == code:
        details = f' Diagnóstico: formato {int(diagnostic[2])}; dimensões {int(diagnostic[3])}x{int(diagnostic[4])}.'
    return IntegrationError('video_native', reasons.get(code, 'O adaptador nativo não entregou uma imagem válida.') + details + ' O login HTTP continua separado deste teste.')


def capture(account, device_id):
    ready, reason = readiness()
    if not ready:
        raise IntegrationError('video_configuration', reason)
    values = (account.access_id, account.access_token, device_id)
    if any(not isinstance(v, str) or not v or len(v) > 8190 or '\n' in v or '\r' in v or '\0' in v for v in values):
        raise IntegrationError('protocol', 'Dados de sessão incompatíveis com o adaptador de imagem.')
    wine = shutil.which('wine') or shutil.which('wine64')
    env = dict(os.environ, WINEDEBUG='-all', WINEDLLOVERRIDES='mscoree,mshtml=',
               WINEPREFIX=str(ROOT / '.local' / 'wine-video'))
    # Vendor code runs as a separate process; never inside the HTTP server.
    # Use a disposable private working directory for any vendor-created files.
    with tempfile.TemporaryDirectory(prefix='yoosee-frame-') as directory:
        process = subprocess.Popen([wine, str(NATIVE / 'yoosee_snapshot.exe')],
                                   cwd=directory, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        try:
            raw, _ = process.communicate(('\n'.join(values) + '\n').encode(), timeout=45)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise IntegrationError('video_timeout', 'A câmera não entregou uma imagem no tempo esperado. Confira se ela abre no aplicativo Yoosee.') from None
        finally:
            # Kill remaining helper processes in this group, if any.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    if process.returncode or not raw.startswith(b'YUV4MPEG2 ') or len(raw) > 26 * 1024 * 1024:
        raise native_failure(process.returncode, raw)
    try:
        result = subprocess.run([shutil.which('ffmpeg'), '-hide_banner', '-loglevel', 'error',
                                 '-protocol_whitelist', 'pipe', '-f', 'yuv4mpegpipe', '-i', 'pipe:0',
                                 '-frames:v', '1', '-vf', "scale='min(1280,iw)':-2", '-f', 'image2pipe',
                                 '-vcodec', 'mjpeg', 'pipe:1'], input=raw, capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        raise IntegrationError('video_decode', 'A conversão da imagem excedeu o tempo esperado.') from None
    image = result.stdout
    if result.returncode or len(image) > 8*1024*1024 or not image.startswith(b'\xff\xd8') or not image.endswith(b'\xff\xd9'):
        raise IntegrationError('video_decode', 'Não foi possível converter o quadro recebido em imagem JPEG.')
    return {'image': 'data:image/jpeg;base64,' + base64.b64encode(image).decode(),
            'message': 'Uma imagem foi recebida da câmera. Esta é uma captura pontual, não uma transmissão ao vivo.'}
