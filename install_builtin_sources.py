from __future__ import annotations

import hashlib
import os
import tempfile
import sys
import zipfile
from pathlib import Path, PurePosixPath


EXPECTED_SHA256 = {
    "01_BARSAN_شناخت_ناوگان_بار_خدمات_استخدام.pdf": "ae291f69cd64d20f2f2240dcb9c1f6b36ad3de0cfa464a38af47f652b45dbf6d",
    "02_BARSAN_عملیات_رانندگان_صف_محدودیت_جابجایی.pdf": "37107a2a85688e914a6925a85ad4fe8f70988871d30581e1c4315d4527d0bc0e",
    "03_BARSAN_پشتیبانی_چرخه_سرویس_مالی_گزارشات.pdf": "9d5313faef1b029cdc96ef3c91c9ee13b7b5d55162a263bbc8a8e6c5d9dfb3f1",
    "04_BARSAN_فرایند_سلب_سرویس_وانت_سبک.pdf": "f53ee58006caaa590a335ee8393420e5c6bc5bd4ee807655ba4d9db1df94689f",
    "preindex.json": "60bb6ef6fdd88a1f669fcd4ec32772441b0231ebdec5c8581042aaa110e15ff6",
    "source_manifest.json": "9299608ce095adac27ded03c46cf1174897f558294de792dceba7ac9d4784e1f",
}
BUNDLE_SHA256 = "142b0e929e8694f505bfe7020a4c9c355f060b1a027a007d17839e152dbdaa2c"
PART_SHA256 = (
    "94ec3ac764eda8632ffa2988111747b88126ba11d828d95722df9642f8aaeeb2",
    "4bdee6feeb078490b96fa4798c226b09489dece3b1f4c645bbb8e22a5da191d3",
    "d3e151d2882f7b9f41e69fed32789897f458f40bf300c24d0e038df88270bd24",
    "e4dfed5357c8c635060a5b36919357e70aa2ddddd7f50f76f52e75377a8bc831",
    "2d8563aab548d5eb2bd38b540e60eaea216b689d9d63e94f92c5992c309fa94f",
    "0a8eb3777002264369e305a5bdf3ca34702987024d9cb3b655d8f2ec130ef158",
    "fbb43249ecc3564e81831e74a84fdee65a0c3f74f971fb984a4d5d9211e289fd",
    "898d37e757e654330903f32d179e04ad5e0a6e870a823ba29b2bc850228356b0",
    "01d06d79fcbce529d2fcdfdb06fdd51827f59081e3aa80a4ff4d57850b55c448",
)


def install(bundle: Path, destination: Path) -> None:
    with zipfile.ZipFile(bundle) as archive:
        infos = archive.infolist()
        names = {info.filename for info in infos}
        if names != set(EXPECTED_SHA256):
            missing = sorted(set(EXPECTED_SHA256) - names)
            unexpected = sorted(names - set(EXPECTED_SHA256))
            raise RuntimeError(f"Invalid built-in bundle contents; missing={missing}, unexpected={unexpected}")
        destination.mkdir(parents=True, exist_ok=True)
        for info in infos:
            relative = PurePosixPath(info.filename)
            if relative.is_absolute() or len(relative.parts) != 1 or ".." in relative.parts or info.is_dir():
                raise RuntimeError(f"Unsafe built-in bundle path: {info.filename}")
            payload = archive.read(info)
            digest = hashlib.sha256(payload).hexdigest()
            if digest != EXPECTED_SHA256[info.filename]:
                raise RuntimeError(f"Built-in bundle checksum mismatch: {info.filename}")
            target = destination / info.filename
            target.write_bytes(payload)
            target.chmod(0o644)


def install_from_parts(parts: list[Path], destination: Path) -> None:
    if len(parts) != len(PART_SHA256):
        raise RuntimeError(f"Expected {len(PART_SHA256)} built-in bundle parts, received {len(parts)}")
    handle, temporary_name = tempfile.mkstemp(prefix="barsan-builtin-", suffix=".zip")
    os.close(handle)
    temporary = Path(temporary_name)
    combined = hashlib.sha256()
    try:
        with temporary.open("wb") as output:
            for index, (part, expected) in enumerate(zip(parts, PART_SHA256, strict=True), start=1):
                payload = part.resolve(strict=True).read_bytes()
                if hashlib.sha256(payload).hexdigest() != expected:
                    raise RuntimeError(f"Built-in bundle part {index} checksum mismatch")
                combined.update(payload)
                output.write(payload)
        if combined.hexdigest() != BUNDLE_SHA256:
            raise RuntimeError("Combined built-in bundle checksum mismatch")
        install(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    expected_argc = len(PART_SHA256) + 2
    if len(sys.argv) != expected_argc:
        part_names = " ".join(f"<part{index:02d}>" for index in range(1, len(PART_SHA256) + 1))
        raise SystemExit(f"usage: install_builtin_sources.py <destination> {part_names}")
    install_from_parts([Path(value) for value in sys.argv[2:]], Path(sys.argv[1]).resolve())
    print(f"BARSAN_BUILTIN_SOURCES_OK files={len(EXPECTED_SHA256)}")


if __name__ == "__main__":
    main()
