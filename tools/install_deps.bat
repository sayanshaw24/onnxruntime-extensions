@echo off
if "%1" == "install" (
  if not exist "%ProgramFiles%\Miniconda3\python3.exe" (
    mklink "%ProgramFiles%\Miniconda3\python3.exe" "%ProgramFiles%\Miniconda3\python.exe"
  )
)
