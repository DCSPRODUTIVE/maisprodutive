"""Build the local x64 adapter and extract its exact DLLs without running them."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from desktop import INSTALLER_SHA256
from video import DLL_HASHES, NATIVE, ROOT, checksum


def prepare(source):
    source = Path(source).expanduser().resolve()
    if not source.is_file() or source.stat().st_size > 120*1024*1024 or checksum(source) != INSTALLER_SHA256:
        raise ValueError('Use o instalador original 1.0.0.8 analisado, com as três partes completas.')
    sevenzip = shutil.which('7z') or shutil.which('7zz')
    compiler = shutil.which('x86_64-w64-mingw32-gcc')
    if not sevenzip or not compiler:
        raise ValueError('Instale primeiro: sudo apt install -y 7zip gcc-mingw-w64-x86-64 wine ffmpeg')
    if NATIVE.exists():
        try:
            manifest = json.loads((NATIVE / 'manifest.json').read_text())
            expected = DLL_HASHES | {'yoosee_snapshot.exe': manifest['bridge_sha256']}
            if manifest['source_sha256'] == checksum(ROOT / 'native' / 'yoosee_snapshot.c') and all(checksum(NATIVE / name) == digest for name, digest in expected.items()):
                print('Adaptador de imagem já estava preparado. Reinicie o servidor e use Testar imagem.')
                return
        except (OSError, ValueError, KeyError, TypeError):
            pass
        raise ValueError('A pasta .local/video já existe com outra versão. Preserve-a ou renomeie-a antes de preparar novamente.')
    NATIVE.parent.mkdir(exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir=NATIVE.parent, prefix='video-build-') as tmp:
        tmp = Path(tmp)
        result = subprocess.run([sevenzip, 'x', '-y', '-bd', '-bso0', '-bsp0', '-o'+str(tmp), str(source),
                                 '*.*/IotVideoSDK.dll', '*.*/msvcp140.dll', '*.*/vcruntime140.dll',
                                 '*.*/vcruntime140_1.dll'], capture_output=True, timeout=60)
        if result.returncode:
            raise ValueError('Falha ao extrair as bibliotecas do instalador.')
        staged = tmp / 'prepared'
        staged.mkdir(mode=0o700)
        for name, digest in DLL_HASHES.items():
            candidates = [p for p in tmp.rglob('*') if p.is_file() and p.name.lower() == name.lower()]
            if len(candidates) != 1 or checksum(candidates[0]) != digest:
                raise ValueError('Biblioteca ausente ou diferente do arquivo analisado: '+name)
            shutil.copyfile(candidates[0], staged / name)
        result = subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-static',
                                 '-o', str(staged / 'yoosee_snapshot.exe'), str(ROOT / 'native' / 'yoosee_snapshot.c')],
                                capture_output=True, timeout=60)
        if result.returncode:
            raise ValueError('Não foi possível compilar o adaptador local. Nenhum binário Windows foi executado.')
        manifest = {'source_sha256': checksum(ROOT / 'native' / 'yoosee_snapshot.c'),
                    'bridge_sha256': checksum(staged / 'yoosee_snapshot.exe')}
        (staged / 'manifest.json').write_text(json.dumps(manifest))
        if NATIVE.exists():
            raise ValueError('A pasta .local/video foi criada por outro processo. Nenhum arquivo existente foi substituído.')
        staged.rename(NATIVE)
    print('Adaptador de imagem preparado. Reinicie o servidor e use Testar imagem em uma câmera.')
    print('O teste executará a biblioteca Windows pelo Wine. Compatibilidade P2P real ainda precisa ser confirmada.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', nargs='?', default=str(Path.home() / 'Yoosee-1.0.0.8.exe'))
    args = parser.parse_args()
    try:
        prepare(args.source)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc) if isinstance(exc, ValueError) else 'Não foi possível preparar o adaptador local.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
