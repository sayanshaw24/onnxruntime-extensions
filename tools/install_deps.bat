@echo off
if "%1" == "install" (
  REM This doesn't work on a CI where Miniconda isn't used.
  if not exist "%ProgramFiles%\Miniconda3\python3.exe" if exist "%ProgramFiles%\Miniconda3\python.exe" (
    mklink "%ProgramFiles%\Miniconda3\python3.exe" "%ProgramFiles%\Miniconda3\python.exe"
  )
)
