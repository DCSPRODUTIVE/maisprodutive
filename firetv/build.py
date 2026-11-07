#!/usr/bin/env python3
"""Build the permission-free Fire TV launcher with a local Android SDK/JDK.

Signing key/password stay in ignored .local, never in the APK or repository.
"""
import argparse
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parent
PRIVATE=ROOT.parent/'.local'/'firetv-signing'


def run(arguments,**options):
    subprocess.run([str(value) for value in arguments],check=True,**options)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--platform',type=Path,required=True,help='Android platform android.jar (API 28+)')
    parser.add_argument('--tools',type=Path,required=True,help='Android SDK build-tools directory')
    args=parser.parse_args()
    platform=args.platform.resolve();tools=args.tools.resolve()
    if not platform.is_file() or not (tools/'aapt').is_file():parser.error('SDK Android ausente.')
    java=shutil.which('java');keytool=shutil.which('keytool')
    if not java or not keytool:parser.error('Instale um JDK com java e keytool.')
    PRIVATE.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(PRIVATE,0o700)
    key=PRIVATE/'release.p12';secret=PRIVATE/'password'
    if key.exists()!=secret.exists():parser.error('Assinatura incompleta; preserve/restaure a chave e sua senha.')
    if not secret.exists():
        fd=os.open(secret,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as file:file.write(secrets.token_urlsafe(40))
    signing_env=dict(os.environ,DCS_FIRETV_STOREPASS=secret.read_text().strip())
    if not key.exists():
        run([keytool,'-genkeypair','-storetype','PKCS12','-keystore',key,'-alias','torre-dcs','-keyalg','RSA',
             '-keysize','2048','-validity','10000','-dname','CN=Torre de Controle DCS','-storepass:env','DCS_FIRETV_STOREPASS',
             '-keypass:env','DCS_FIRETV_STOREPASS','-noprompt'],env=signing_env)
    os.chmod(key,0o600);os.chmod(secret,0o600)
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    output=dist/'torre-de-controle-firetv.apk'
    with tempfile.TemporaryDirectory(prefix='firetv-build-') as folder:
        stage=Path(folder);classes=stage/'classes';classes.mkdir()
        sources=sorted((ROOT/'src').rglob('*.java'))
        run([java,'com.sun.tools.javac.Main','-source','8','-target','8','-Xlint:-options','-parameters','-encoding','UTF-8',
             '-bootclasspath',platform,'-d',classes,*sources])
        if (tools/'lib'/'d8.jar').is_file():
            run([java,'-cp',tools/'lib'/'d8.jar','com.android.tools.r8.D8','--min-api','21','--lib',platform,
                 '--output',stage,*sorted(classes.rglob('*.class'))])
        else:
            run([java,'-cp',tools/'lib'/'dx.jar','com.android.dx.command.Main','--dex','--output='+str(stage/'classes.dex'),classes])
        unsigned=stage/'unsigned.apk'
        run([tools/'aapt','package','-f','-M',ROOT/'AndroidManifest.xml','-S',ROOT/'res','-I',platform,'-F',unsigned])
        with zipfile.ZipFile(unsigned,'a',compression=zipfile.ZIP_DEFLATED) as apk:apk.write(stage/'classes.dex','classes.dex')
        aligned=stage/'aligned.apk';run([tools/'zipalign','-f','4',unsigned,aligned])
        signer=[java,'-jar',tools/'lib'/'apksigner.jar']
        run([*signer,'sign','--ks',key,'--ks-key-alias','torre-dcs','--ks-pass','env:DCS_FIRETV_STOREPASS',
             '--key-pass','env:DCS_FIRETV_STOREPASS','--v1-signing-enabled','true','--v2-signing-enabled','true',
             '--out',output,aligned],env=signing_env)
        run([*signer,'verify','--verbose',output])
        run([tools/'zipalign','-c','4',output])
    checksum=hashlib.sha256(output.read_bytes()).hexdigest()
    (dist/'SHA256SUMS').write_text(checksum+'  '+output.name+'\n')
    print(f'APK pronto: {output} ({output.stat().st_size} bytes)')


if __name__=='__main__':main()
