#!/bin/bash
set -e

# Python 虛擬環境一鍵建置與安裝腳本 (使用 uv 版)
echo "====== 正在初始化 Python 虛擬環境 (使用 uv) ======"

# 1. 檢查是否安裝 Python 3
if ! command -v python3 &> /dev/null; then
    echo "[錯誤] 系統未安裝 python3，請先安裝 Python 3！"
    exit 1
fi

# 2. 檢查是否安裝 uv，若無則自動透過 pip 安裝
if ! command -v uv &> /dev/null; then
    echo "[資訊] 未偵測到 uv 工具，正在透過 pip 為您安裝 uv..."
    python3 -m pip install --user uv || python3 -m pip install uv
fi

# 再次檢查 uv 是否安裝成功
if ! command -v uv &> /dev/null; then
    echo "[錯誤] 無法安裝 uv！請手動參考官網安裝：https://github.com/astral-sh/uv"
    exit 1
fi

echo "[資訊] 已偵測到 uv 版本: $(uv --version)"

# 3. 使用 uv 建立虛擬環境
if [ ! -d ".venv" ]; then
    echo "[資訊] 正在使用 uv 建立虛擬環境於 .venv/..."
    uv venv .venv
else
    echo "[資訊] 虛擬環境 .venv/ 已經存在，略過建立步驟。"
fi

# 4. 使用 uv pip 安裝依賴與本專案 (開發者模式)
echo "[資訊] 正在使用 uv 安裝專案依賴與 CLI 工具..."
uv pip install -p .venv -e .

echo "==============================================="
echo "[成功] 虛擬環境建置完成！"
echo "請在終端機執行以下命令以啟用虛擬環境："
echo ""
echo "    source .venv/bin/activate"
echo ""
echo "啟用後，您就可以在任何地方直接執行 CLI 指令："
echo ""
echo "    vm-connector --help"
echo "==============================================="
