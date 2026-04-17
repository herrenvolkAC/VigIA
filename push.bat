@echo off
cd /d C:\Ingenieria\VigIA
set /p commit_msg="Ingresa el mensaje del commit: "
git add .
git commit -m "%commit_msg%"
git push
pause
