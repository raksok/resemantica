from __future__ import annotations

from pathlib import Path
import zipfile


def rebuild_epub(unpacked_dir: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    file_paths = sorted(
        file_path
        for file_path in unpacked_dir.rglob("*")
        if file_path.is_file()
    )
    rel_paths = [file_path.relative_to(unpacked_dir).as_posix() for file_path in file_paths]

    with zipfile.ZipFile(output_path, "w") as archive:
        if "mimetype" in rel_paths:
            archive.write(
                unpacked_dir / "mimetype",
                arcname="mimetype",
                compress_type=zipfile.ZIP_STORED,
            )

        for relative_path in rel_paths:
            if relative_path == "mimetype":
                continue
            archive.write(
                unpacked_dir / relative_path,
                arcname=relative_path,
                compress_type=zipfile.ZIP_DEFLATED,
            )

    return output_path

