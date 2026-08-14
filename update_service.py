from __future__ import annotations

import hashlib
import json
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app_version import APP_VERSION


GITHUB_REPOSITORY = "TANGuoGUO/entp-manual"
UPDATE_MANIFEST_URL = (
    f"https://github.com/{GITHUB_REPOSITORY}/releases/latest/download/update.json"
)
MAX_RELEASE_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_INSTALLER_BYTES = 250 * 1024 * 1024
USER_AGENT = f"ENTP-Manual/{APP_VERSION}"


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag_name: str
    notes: str
    html_url: str
    asset_name: str
    download_url: str
    size: int
    sha256: str


def parse_version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", value.strip())
    if not match:
        raise UpdateError(f"无法识别版本号：{value}")
    return tuple(int(part) for part in match.groups())


def is_newer_version(candidate: str, current: str = APP_VERSION) -> bool:
    return parse_version(candidate) > parse_version(current)


def _read_limited(response, limit: int) -> bytes:
    payload = response.read(limit + 1)
    if len(payload) > limit:
        raise UpdateError("GitHub 返回的更新信息过大")
    return payload


def fetch_latest_release(
    *,
    opener=urllib.request.urlopen,
    timeout: float = 12,
) -> ReleaseInfo:
    request = urllib.request.Request(
        UPDATE_MANIFEST_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(
                _read_limited(response, MAX_RELEASE_RESPONSE_BYTES).decode("utf-8")
            )
    except UpdateError:
        raise
    except Exception as error:
        raise UpdateError(f"无法连接 GitHub：{error}") from error

    if not isinstance(payload, dict):
        raise UpdateError("GitHub 返回了无法识别的更新信息")
    version = str(payload.get("version") or "").strip().removeprefix("v")
    parse_version(version)
    tag_name = str(payload.get("tag_name") or f"v{version}").strip()
    if tag_name != f"v{version}":
        raise UpdateError("更新清单中的版本标记不一致")
    expected_asset = f"ENTP-Manual-{version}-Setup.exe"
    asset_name = str(payload.get("asset_name") or "")
    if asset_name != expected_asset:
        raise UpdateError(f"这个版本缺少安装包：{expected_asset}")

    download_url = str(payload.get("download_url") or "")
    expected_prefix = (
        f"https://github.com/{GITHUB_REPOSITORY}/releases/download/{tag_name}/"
    )
    if not download_url.startswith(expected_prefix):
        raise UpdateError("安装包下载地址不属于本项目的 GitHub Release")
    size = int(payload.get("size") or 0)
    if size <= 0 or size > MAX_INSTALLER_BYTES:
        raise UpdateError("安装包大小异常，已停止更新")
    digest = str(payload.get("sha256") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        raise UpdateError("安装包没有可验证的 SHA-256 摘要")

    return ReleaseInfo(
        version=version,
        tag_name=tag_name,
        notes=str(payload.get("notes") or "").strip(),
        html_url=str(payload.get("html_url") or ""),
        asset_name=expected_asset,
        download_url=download_url,
        size=size,
        sha256=digest.lower(),
    )


def download_release(
    release: ReleaseInfo,
    destination_dir: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    opener=urllib.request.urlopen,
    timeout: float = 60,
) -> Path:
    if Path(release.asset_name).name != release.asset_name:
        raise UpdateError("安装包文件名不安全")
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / release.asset_name
    partial = target.with_suffix(f"{target.suffix}.part")
    digest = hashlib.sha256()
    downloaded = 0
    request = urllib.request.Request(
        release.download_url,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with opener(request, timeout=timeout) as response, partial.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > MAX_INSTALLER_BYTES or downloaded > release.size:
                    raise UpdateError("下载内容超过发布页标注的大小")
                output.write(chunk)
                digest.update(chunk)
                if progress is not None:
                    progress(downloaded, release.size)
        if downloaded != release.size:
            raise UpdateError("安装包下载不完整，请稍后重试")
        if digest.hexdigest().lower() != release.sha256.lower():
            raise UpdateError("安装包校验失败，文件可能损坏")
        partial.replace(target)
        return target
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    except Exception as error:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"下载安装包失败：{error}") from error


def launch_silent_update(
    installer: Path,
    *,
    popen=subprocess.Popen,
):
    if not installer.is_file():
        raise UpdateError("下载的安装包不存在")
    arguments = [
        str(installer),
        "/SP-",
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/CLOSEAPPLICATIONS",
    ]
    try:
        return popen(arguments, close_fds=True)
    except Exception as error:
        raise UpdateError(f"无法启动更新程序：{error}") from error
