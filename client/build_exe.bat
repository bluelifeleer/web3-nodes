@echo off
echo ====================== 开始打包节点客户端 ======================
cd /d "%~dp0.."
pip install -r requirements.txt
if exist node.ico (
    pyinstaller -F -w -i node.ico client\main.py
) else (
    pyinstaller -F -w client\main.py
)
if not exist dist\node_config.json copy client\node_config.example.json dist\node_config.json
if exist .env if not exist dist\.env copy .env dist\.env
echo ====================== 打包完成！EXE在 dist 文件夹 ======================
pause
