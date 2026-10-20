"""Import only the known Windows client's parameters, without running its code."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

from desktop import DesktopProfile, EXECUTABLE_SHA256, INSTALLER_SHA256, profile_path
from yoosee import IntegrationError


def read_pe_string(binary, rva):
    try:
        if binary[:2] != b"MZ":
            raise ValueError
        pe = struct.unpack_from("<I", binary, 60)[0]
        if binary[pe:pe + 4] != b"PE\0\0":
            raise ValueError
        machine, count = struct.unpack_from("<HH", binary, pe + 4)
        optional_size = struct.unpack_from("<H", binary, pe + 20)[0]
        if machine != 0x8664 or count > 96:
            raise ValueError
        sections = pe + 24 + optional_size
        for index in range(count):
            pos = sections + index * 40
            size, address, raw_size, offset = struct.unpack_from("<IIII", binary, pos + 8)
            if address <= rva < address + raw_size:
                start = offset + rva - address
                end = binary.index(b"\0", start, start + 200)
                return binary[start:end].decode("ascii")
    except (ValueError, struct.error, UnicodeError):
        pass
    raise IntegrationError("input", "Executável Windows incompatível com o layout analisado.")


def extract_profile(binary):
    if hashlib.sha256(binary).hexdigest() != EXECUTABLE_SHA256:
        raise IntegrationError("input", "Executável diferente do Yoosee 1.0.0.8 analisado. Nenhum parâmetro foi importado.")
    # RVAs verified at UserMobileLogin's QJsonValue calls; never print values.
    return DesktopProfile(read_pe_string(binary, 0x5BB5A8), read_pe_string(binary, 0x5BB5E0))


def load_binary(source, sevenzip=None):
    source = Path(source).expanduser().resolve()
    if not source.is_file() or source.stat().st_size > 120 * 1024 * 1024:
        raise IntegrationError("input", "Selecione o instalador 1.0.0.8 ou seu Yoosee.exe extraído.")
    raw = source.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    if checksum == EXECUTABLE_SHA256:
        return raw
    if checksum != INSTALLER_SHA256:
        raise IntegrationError("input", "Este arquivo não é o instalador 1.0.0.8 que foi analisado. Não execute nem renomeie outra versão para tentar importar.")
    tool = sevenzip or shutil.which("7z") or shutil.which("7zz")
    if not tool:
        raise IntegrationError("configuration", "Falta a ferramenta de extração. Instale com: sudo apt install -y 7zip")
    # Only the trusted extraction utility runs; never invoke the uploaded EXE.
    with tempfile.TemporaryDirectory(prefix="yoosee-import-") as tmp:
        result = subprocess.run([str(tool), "x", "-y", "-bd", "-bso0", "-bsp0", "-o" + tmp,
                                 str(source), "*.*/Yoosee.exe"], capture_output=True, timeout=60)
        if result.returncode:
            raise IntegrationError("input", "A extração falhou. O instalador pode estar incompleto.")
        candidates = list(Path(tmp).rglob("Yoosee.exe"))
        if len(candidates) != 1:
            raise IntegrationError("input", "Não foi encontrado um único Yoosee.exe compatível no instalador.")
        return candidates[0].read_bytes()


def save_profile(profile, target=None):
    target = Path(target) if target is not None else profile_path()
    data = {"schema": 1, "source_sha256": EXECUTABLE_SHA256,
            "app_id": profile.app_id, "app_token": profile.app_token}
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Preserve any pre-existing local configuration; only accept identical data.
    if target.exists():
        if target.stat().st_size <= 8192 and json.loads(target.read_text()) == data:
            return False
        raise IntegrationError("configuration", "Já existe um perfil diferente. Preserve-o antes de substituir a configuração.")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream)
    return True


def main():
    parser = argparse.ArgumentParser(description="Preparar integração Windows sem instalar ou executar o cliente")
    parser.add_argument("source", nargs="?", default=str(Path.home() / "Yoosee-1.0.0.8.exe"))
    parser.add_argument("--sevenzip", help="Caminho opcional para uma instalação confiável de 7z")
    parser.add_argument("--output", help="Arquivo local de configuração; padrão: .local/yoosee-desktop.json")
    args = parser.parse_args()
    try:
        profile = extract_profile(load_binary(args.source, args.sevenzip))
        created = save_profile(profile, args.output)
        print("Perfil Windows preparado." if created else "Perfil Windows já estava preparado.")
        print("Reinicie o servidor e use Testar login Windows. Nenhuma senha de conta foi solicitada ou salva.")
        return 0
    except (IntegrationError, OSError, ValueError, subprocess.TimeoutExpired):
        # Avoid leaking local profile contents, archive data or extracted strings.
        import sys
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, IntegrationError) else "Não foi possível importar o perfil Windows. Confira o arquivo, a ferramenta 7zip e as permissões locais.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
