# Bundled FFmpeg Runtime

The Windows offline bundle builder must manually place a complete Windows x64
FFmpeg runtime in this directory. The project does not download FFmpeg and does
not put FFmpeg binaries in `wheelhouse/`.

Expected delivery layout:

```text
runtime/
  ffmpeg/
    bin/
      ffplay.exe
      ffmpeg.exe
      ffprobe.exe
      *.dll
```

Keep every DLL required by the selected FFmpeg build beside the executables.
Run `WINDOWS_CHECK.bat` on the target computer to execute
`runtime\ffmpeg\bin\ffplay.exe -version` before the classroom demo.
