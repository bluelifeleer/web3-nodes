@echo off
echo ====================== 开始打包节点客户端 ======================
cd /d "%~dp0.."
pip install -r requirements.txt
if exist node.ico (
    pyinstaller -F -w -i node.ico client\main.py
) else (
    pyinstaller -F -w client\main.py
)
echo ====================== 打包完成！EXE在 dist 文件夹 ======================
pause
