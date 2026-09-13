"""Streaming FFmpeg encoders for editor-ready overlay assets."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import TracebackType

from PIL import Image


class FFmpegEncoder:
    """Stream raw Pillow frames into one FFmpeg output."""

    def __init__(
        self,
        output: str | Path,
        *,
        width: int,
        height: int,
        fps: int,
        kind: str,
        overwrite: bool = False,
    ) -> None:
        self.output = Path(output)
        self.width = width
        self.height = height
        self.fps = fps
        self.kind = kind
        self.overwrite = overwrite
        self.process: subprocess.Popen[bytes] | None = None
        self.expected_mode = "RGBA" if kind == "overlay" else "RGB"

    def _command(self) -> list[str]:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError(
                "FFmpeg is required to render overlay video but was not found on PATH"
            )
        if self.kind not in {"overlay", "matte", "preview"}:
            raise ValueError(f"unsupported encoder kind: {self.kind}")
        if self.output.exists() and not self.overwrite:
            raise FileExistsError(
                f"output already exists: {self.output}; use --overwrite to replace it"
            )

        input_pixel_format = "rgba" if self.kind == "overlay" else "rgb24"
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if self.overwrite else "-n",
            "-f",
            "rawvideo",
            "-pixel_format",
            input_pixel_format,
            "-video_size",
            f"{self.width}x{self.height}",
            "-framerate",
            str(self.fps),
            "-i",
            "pipe:0",
            "-an",
        ]
        if self.kind == "overlay":
            command.extend(
                [
                    "-c:v",
                    "prores_ks",
                    "-profile:v",
                    "4",
                    "-pix_fmt",
                    "yuva444p10le",
                    "-alpha_bits",
                    "16",
                    "-vendor",
                    "apl0",
                ]
            )
        elif self.kind == "matte":
            command.extend(
                [
                    "-c:v",
                    "prores_ks",
                    "-profile:v",
                    "3",
                    "-pix_fmt",
                    "yuv422p10le",
                    "-vendor",
                    "apl0",
                ]
            )
        else:
            command.extend(
                [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                ]
            )
        command.append(str(self.output))
        return command

    def __enter__(self) -> FFmpegEncoder:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            self._command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
        )
        return self

    def write(self, frame: Image.Image) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("FFmpeg encoder has not been started")
        if frame.mode != self.expected_mode:
            raise ValueError(
                f"{self.kind} encoder expects {self.expected_mode} frames, got {frame.mode}"
            )
        if frame.size != (self.width, self.height):
            raise ValueError(
                f"encoder expects {self.width}x{self.height} frames, got "
                f"{frame.width}x{frame.height}"
            )
        try:
            self.process.stdin.write(frame.tobytes())
        except BrokenPipeError as error:
            details = self._read_error()
            raise RuntimeError(f"FFmpeg stopped while writing {self.output}: {details}") from error

    def _read_error(self) -> str:
        if self.process is None or self.process.stderr is None:
            return "no diagnostic output"
        return self.process.stderr.read().decode("utf-8", errors="replace").strip()

    def close(self) -> None:
        if self.process is None:
            return
        if self.process.stdin is not None and not self.process.stdin.closed:
            self.process.stdin.close()
        details = self._read_error()
        return_code = self.process.wait()
        self.process = None
        if return_code:
            raise RuntimeError(f"FFmpeg failed to create {self.output}: {details}")

    def abort(self) -> None:
        if self.process is None:
            return
        if self.process.stdin is not None and not self.process.stdin.closed:
            self.process.stdin.close()
        self.process.terminate()
        self.process.wait()
        self.process = None

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if exception_type is None:
            self.close()
        else:
            self.abort()
