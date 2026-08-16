from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageFilter


WINDOWS_ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def render_frame(source: Image.Image, size: int) -> Image.Image:
    frame = source.resize((size, size), Image.Resampling.LANCZOS, reducing_gap=3.0)
    if size <= 64:
        # Small Windows icons benefit from a restrained optical sharpening pass.
        frame = frame.filter(
            ImageFilter.UnsharpMask(
                radius=0.55 if size <= 32 else 0.75,
                percent=145 if size <= 32 else 115,
                threshold=2,
            )
        )
    return frame


def build_icon(source_path: Path, output_path: Path) -> None:
    with Image.open(source_path) as opened:
        source = opened.convert("RGBA")

    if source.width != source.height:
        raise ValueError(f"Windows icon source must be square: {source_path}")
    if source.width < max(WINDOWS_ICON_SIZES):
        raise ValueError(
            f"Windows icon source must be at least 256x256: {source_path}"
        )

    frames = [render_frame(source, size) for size in WINDOWS_ICON_SIZES]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    frames[-1].save(
        temporary,
        format="ICO",
        sizes=[(size, size) for size in WINDOWS_ICON_SIZES],
        append_images=frames[:-1],
        bitmap_format="png",
    )
    temporary.replace(output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a multi-resolution Windows ICO from the app logo."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("outputs", nargs="+", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for output in args.outputs:
        build_icon(args.source.resolve(), output.resolve())


if __name__ == "__main__":
    main()
