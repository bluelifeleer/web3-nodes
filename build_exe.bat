@echo off
echo ====================== 开始打包节点客户端 ======================
pip install pyinstaller requests
pyinstaller -F -w -i node.ico node_final.py
echo ====================== 打包完成！EXE在 dist 文件夹 ======================
pause