@echo off
if "%1" == "install" (
  dir "%ProgramFiles%"
  if not exist "%ProgramFiles%\Miniconda3\python3.exe" and exist "%ProgramFiles%\Miniconda3\python.exe" (
    mklink "%ProgramFiles%\Miniconda3\python3.exe" "%ProgramFiles%\Miniconda3\python.exe"
  )
)
