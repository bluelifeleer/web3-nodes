#!/bin/zsh
echo "========== Mac节点客户端开始打包 =========="
SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR/.."
# 安装依赖
pip3 install -r requirements.txt
# 打包命令：单文件、无控制台、MacAPP格式
pyinstaller -F -w --noconsole client/node_mac.py
echo "========== Mac打包完成 =========="
echo "成品路径：./dist/node_mac（Mac可执行文件）"
echo "MacAPP格式文件：./dist/node_mac.app"
