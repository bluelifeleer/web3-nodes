@echo off
echo ====================== 开始打包节点客户端 ======================
pip install -r requirements.txt
if exist node.ico (
    pyinstaller -F -w -i node.ico client.py
) else (
    pyinstaller -F -w client.py
)
echo ====================== 打包完成！EXE在 dist 文件夹 ======================
pause
