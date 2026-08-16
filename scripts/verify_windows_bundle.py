from __future__ import annotations

import argparse
import re
from pathlib import Path


PYTHON_MAGIC = {
    "3.12": bytes.fromhex("cb0d0d0a"),
    "3.13": bytes.fromhex("f30d0d0a"),
}


def verify_bundle(bundle: Path, python_version: str) -> tuple[int, int]:
    if python_version not in PYTHON_MAGIC:
        raise ValueError(f"unsupported Python version: {python_version}")
    if not bundle.is_dir():
        raise ValueError(f"bundle directory does not exist: {bundle}")

    compact_version = python_version.replace(".", "")
    expected_runtime = f"python{compact_version}.dll"
    runtime_dlls = sorted(path.name for path in bundle.glob("python3??.dll"))
    if runtime_dlls != [expected_runtime]:
        raise ValueError(
            "bundle must contain exactly one versioned Python runtime "
            f"({expected_runtime}); found: {runtime_dlls or 'none'}"
        )

    expected_magic = PYTHON_MAGIC[python_version]
    pyc_files = list(bundle.rglob("*.pyc"))
    if not pyc_files:
        raise ValueError("bundle contains no Python bytecode")
    bad_bytecode = []
    for path in pyc_files:
        with path.open("rb") as stream:
            actual_magic = stream.read(4)
        if actual_magic != expected_magic:
            bad_bytecode.append((path, actual_magic.hex()))
            if len(bad_bytecode) >= 10:
                break
    if bad_bytecode:
        details = ", ".join(
            f"{path.relative_to(bundle)}={magic}" for path, magic in bad_bytecode
        )
        raise ValueError(
            f"bytecode does not match Python {python_version} "
            f"(expected {expected_magic.hex()}): {details}"
        )

    expected_abi = f"cp{compact_version}"
    incompatible_extensions = []
    for path in bundle.rglob("*.pyd"):
        match = re.search(r"\.cp(\d{3})-", path.name)
        if match and f"cp{match.group(1)}" != expected_abi:
            incompatible_extensions.append(path.relative_to(bundle))
    if incompatible_extensions:
        raise ValueError(
            f"extensions do not match {expected_abi}: {incompatible_extensions[:10]}"
        )

    return len(pyc_files), sum(1 for _ in bundle.rglob("*.pyd"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the embedded Python runtime and bytecode in a Flet bundle."
    )
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--python-version", required=True)
    arguments = parser.parse_args()
    try:
        bytecode_count, extension_count = verify_bundle(
            arguments.bundle.resolve(), arguments.python_version
        )
    except ValueError as error:
        parser.error(str(error))
    print(
        f"Verified Python {arguments.python_version}: "
        f"{bytecode_count} bytecode files, {extension_count} native extensions."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
