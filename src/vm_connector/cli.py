import os
import sys
import argparse

# 預設的 config.yaml 範本內容 (避免 init 時依賴 pyyaml)
CONFIG_TEMPLATE = """# VMware & SSH 控制工具設定檔

# 虛擬機驅動設定 (可用值: fusion, workstation, esxi, none)
# - fusion: 使用 macOS 的 vmrun 控制本機 VMware Fusion
# - workstation: 使用 Windows/Linux 的 vmrun 控制本機 VMware Workstation
# - esxi: 使用 pyVmomi 透過網路 API 控制遠端 ESXi / vCenter 伺服器
# - none: 僅使用 SSH 連線，跳過開關機控制
vmware_type: fusion

# VMware Fusion/Workstation 本機設定 (當 vmware_type 為 fusion 或 workstation 時使用)
local_vm:
  # 虛擬機設定檔 (.vmx) 的絕對路徑
  vmx_path: "/Users/yourusername/Virtual Machines.localized/Ubuntu.vmwarevm/Ubuntu.vmx"
  # vmrun 執行檔的路徑。若留空，程式會嘗試自動尋找預設路徑：
  # - macOS Fusion: /Applications/VMware Fusion.app/Contents/Library/vmrun
  # - Windows Workstation: C:\\Program Files (x86)\\VMware\\VMware Workstation\\vmrun.exe
  # - Linux Workstation: /usr/bin/vmrun
  vmrun_path: ""

# VMware ESXi / vCenter 遠端設定 (當 vmware_type 為 esxi 時使用)
esxi_vm:
  host: "192.168.1.100"
  port: 443
  username: "root"
  password: "your_esxi_password"
  # 虛擬機在 ESXi/vCenter 中的顯示名稱 (VM Name)
  vm_name: "My_Ubuntu_VM"

# 虛擬機 Guest OS 的 SSH 連線設定
ssh:
  # 虛擬機的 IP 位址。
  # 提示: 如果 vmware_type 不是 none，程式在執行時若發現 host 未填寫，
  # 會自動嘗試向 VMware 獲取虛擬機的 Guest IP。
  host: "192.168.x.x"
  port: 22
  username: "ubuntu"
  
  # 驗證方式 (擇一填寫，若設定 key_path 則優先使用金鑰驗證)
  password: "your_ssh_password"
  key_path: ""            # 金鑰檔案路徑 (例如 "/Users/yourusername/.ssh/id_rsa")
  key_password: ""        # 若金鑰有密碼保護，請填寫此欄位，否則留空

# Socket 連線設定 (本機作為 Client 連線到 VM 內部的 Socket Server)
socket:
  # Socket Server 的 IP 位址。留空時自動取用 ssh.host 的值。
  host: ""
  # Socket Server 監聽的 Port
  port: 9999
  # 連線逾時秒數 (預設 10)
  timeout: 10
  # 文字資料的編碼格式 (預設 utf-8)
  encoding: "utf-8"
"""


def init_config(config_path="config.yaml"):
    """在當前目錄建立設定檔範本"""
    if os.path.exists(config_path):
        print(f"[資訊] 設定檔 {config_path} 已經存在，跳過建立。")
        return
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(CONFIG_TEMPLATE)
        print(f"[成功] 已建立設定檔範本: {config_path}")
        print("請開啟此檔案，填寫您的虛擬機設定與 SSH 帳密。")
    except Exception as e:
        print(f"[錯誤] 無法建立設定檔: {e}", file=sys.stderr)
        sys.exit(1)


def load_config(config_path="config.yaml"):
    """載入並解析 YAML 設定檔"""
    if not os.path.exists(config_path):
        print(f"[錯誤] 找不到設定檔: {config_path}", file=sys.stderr)
        print("請先執行 `vm-connector init` 產生設定檔，並填寫正確設定。", file=sys.stderr)
        sys.exit(1)
        
    try:
        import yaml
    except ImportError:
        print("[錯誤] 執行此操作需要 pyyaml 套件，請使用虛擬環境或執行 `pip install pyyaml` 安裝。", file=sys.stderr)
        sys.exit(1)
        
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"[錯誤] 解析設定檔 {config_path} 失敗: {e}", file=sys.stderr)
        sys.exit(1)


def get_ssh_client(config, vm_manager):
    """取得連線後的 SSH Client 實例"""
    ssh_cfg = config.get("ssh", {})
    host = ssh_cfg.get("host")
    
    # 判斷 host 是否為未設定或佔位符
    is_placeholder = not host or host == "192.168.x.x" or host.strip() == ""
    
    if is_placeholder:
        # 嘗試向虛擬機管理模組查詢動態 IP
        vm_type = config.get("vmware_type", "none").lower()
        if vm_type != "none" and vm_manager:
            print("[資訊] 設定檔中未指定 SSH IP，正在嘗試透過 VMware 獲取虛擬機的 Guest IP...")
            
            # 先檢查 VM 狀態
            status = vm_manager.get_status()
            if status != "running":
                print(f"[錯誤] 虛擬機目前未啟動 (目前狀態: {status})，無法獲取 IP。", file=sys.stderr)
                print("請先執行 `vm-connector vm-start` 將虛擬機開機。", file=sys.stderr)
                sys.exit(1)
                
            ip = vm_manager.get_ip()
            if ip:
                print(f"[資訊] 成功獲取虛擬機 IP: {ip}")
                host = ip
            else:
                print("[錯誤] 無法取得虛擬機 IP。請確認 Guest OS 已啟動且已安裝 VMware Tools，或者手動在 config.yaml 設定 ssh.host。", file=sys.stderr)
                sys.exit(1)
        else:
            print("[錯誤] 設定檔中未指定 SSH IP，且虛擬機驅動設定為 none。請在 config.yaml 填寫 ssh.host。", file=sys.stderr)
            sys.exit(1)

    port = ssh_cfg.get("port", 22)
    username = ssh_cfg.get("username")
    if not username:
        print("[錯誤] 設定檔中未指定 SSH 使用者名稱 (ssh.username)。", file=sys.stderr)
        sys.exit(1)
        
    from .ssh_client import SSHClientWrapper
    client = SSHClientWrapper(host, port, username, ssh_cfg)
    client.connect()
    return client


def get_socket_host(config: dict) -> str:
    """取得 Socket Server 的 IP：優先用 socket.host，若未填則取用 ssh.host"""
    socket_cfg = config.get("socket", {})
    host = socket_cfg.get("host", "").strip()
    if not host:
        ssh_host = config.get("ssh", {}).get("host", "").strip()
        if ssh_host and ssh_host != "192.168.x.x":
            return ssh_host
        print(
            "[錯誤] 未設定 Socket Server IP。請在 config.yaml 填寫 socket.host 或 ssh.host。",
            file=sys.stderr,
        )
        sys.exit(1)
    return host


def handle_socket_send(args, config):
    """處理 socket-send 子指令邏輯"""
    socket_cfg = config.get("socket", {})
    host = args.host or get_socket_host(config)
    port = args.port or socket_cfg.get("port", 9999)
    timeout = socket_cfg.get("timeout", 10)
    encoding = socket_cfg.get("encoding", "utf-8")

    from .socket_client import SocketClient

    # 確認只指定了一種資料來源
    sources = [s for s in [args.text, args.json, args.file] if s is not None]
    if len(sources) == 0:
        print("[錯誤] 請至少指定一種傳送方式：--text、--json 或 --file。", file=sys.stderr)
        sys.exit(1)
    if len(sources) > 1:
        print("[錯誤] 請只選擇一種傳送方式：--text、--json 或 --file（不可同時使用）。", file=sys.stderr)
        sys.exit(1)

    try:
        with SocketClient(host, port, timeout=timeout, encoding=encoding) as client:
            if args.text is not None:
                client.send_text(args.text)
            elif args.json is not None:
                import json
                try:
                    data = json.loads(args.json)
                except json.JSONDecodeError as e:
                    print(f"[錯誤] JSON 格式錯誤: {e}", file=sys.stderr)
                    sys.exit(1)
                client.send_json(data)
            elif args.file is not None:
                if not os.path.exists(args.file):
                    print(f"[錯誤] 找不到檔案: {args.file}", file=sys.stderr)
                    sys.exit(1)
                with open(args.file, "rb") as f:
                    data = f.read()
                client.send_bytes(data)

            # 若啟用接收回應
            if args.receive:
                response = client.receive_text()
                if response:
                    print(f"[回應] {response}")
    except Exception as e:
        print(f"[錯誤] Socket 操作失敗: {e}", file=sys.stderr)
        sys.exit(1)


def handle_bg_run(args, config, vm_manager):
    """處理 bg-run 子指令邏輯"""
    client = get_ssh_client(config, vm_manager)
    try:
        use_nohup = not args.no_nohup
        pid = client.execute_background(args.cmd, use_nohup=use_nohup)
        if pid:
            print(f"[成功] 背景行程 PID: {pid}")
        sys.exit(0)
    except Exception as e:
        print(f"[錯誤] 背景執行失敗: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(
        description="VMware 虛擬機管理與 SSH 互動式終端機控制工具 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", help="子指令功能")
    
    # 1. init
    subparsers.add_parser("init", help="在當前目錄產生設定檔範本 (config.yaml)")
    
    # 2. vm-start
    subparsers.add_parser("vm-start", help="啟動 VMware 虛擬機")
    
    # 3. vm-stop
    stop_parser = subparsers.add_parser("vm-stop", help="關閉 VMware 虛擬機")
    stop_parser.add_argument("--force", action="store_true", help="強制斷電關機 (Hard Power Off)")
    
    # 4. vm-status
    subparsers.add_parser("vm-status", help="查詢虛擬機運作狀態 (開機/關機)")
    
    # 5. vm-ip
    subparsers.add_parser("vm-ip", help="向虛擬機 Tools 獲取虛擬機內網 IP")
    
    # 6. run
    run_parser = subparsers.add_parser("run", help="在虛擬機中執行單一命令並輸出結果")
    run_parser.add_argument("cmd", help="欲執行的命令，例如 'ls -la' 或 'uname -a'")
    
    # 7. ssh
    subparsers.add_parser("ssh", help="與虛擬機建立互動式 SSH 終端機連線 (支援 Tab、Ctrl+C)")

    # 8. socket-send
    socket_parser = subparsers.add_parser(
        "socket-send",
        help="連線到 VM 內部的 Socket Server 並傳送資料"
    )
    socket_send_group = socket_parser.add_mutually_exclusive_group(required=True)
    socket_send_group.add_argument("--text", metavar="MESSAGE", help="傳送文字訊息")
    socket_send_group.add_argument("--json", metavar="JSON", help="傳送 JSON 字串 (例如 '{\"action\": \"start\"}')")
    socket_send_group.add_argument("--file", metavar="FILE", help="讀取本機檔案並以二進位方式傳送")
    socket_parser.add_argument("--host", metavar="HOST", default=None, help="覆寫 config 中的 socket.host")
    socket_parser.add_argument("--port", metavar="PORT", type=int, default=None, help="覆寫 config 中的 socket.port")
    socket_parser.add_argument("--receive", action="store_true", help="傳送後等待並顯示 Server 的回應")

    # 9. bg-run
    bg_parser = subparsers.add_parser(
        "bg-run",
        help="透過 SSH 在 VM 背景執行指令（nohup 包裝，立即返回 PID）"
    )
    bg_parser.add_argument("cmd", help="要在 VM 中背景執行的指令，例如 '/opt/myapp/start.sh'")
    bg_parser.add_argument(
        "--no-nohup", action="store_true",
        help="不使用 nohup 包裝（適用於本身有 daemon 機制的程式）"
    )

    args = parser.parse_args()

    # 如果沒給指令，則顯示說明
    if not args.command:
        parser.print_help()
        sys.exit(0)

    # init 指令不需載入 config
    if args.command == "init":
        init_config()
        sys.exit(0)

    # 載入設定檔與建立 VM Manager
    config = load_config()
    from .vm_manager import get_vm_manager
    try:
        vm_manager = get_vm_manager(config)
    except Exception as e:
        print(f"[錯誤] 初始化虛擬機管理器失敗: {e}", file=sys.stderr)
        sys.exit(1)

    # 執行指令邏輯
    if args.command == "vm-start":
        success = vm_manager.start()
        sys.exit(0 if success else 1)
        
    elif args.command == "vm-stop":
        success = vm_manager.stop(force=args.force)
        sys.exit(0 if success else 1)
        
    elif args.command == "vm-status":
        status = vm_manager.get_status()
        print(f"虛擬機狀態: {status}")
        sys.exit(0)
        
    elif args.command == "vm-ip":
        ip = vm_manager.get_ip()
        if ip:
            print(f"虛擬機 IP 地址: {ip}")
        else:
            print("[錯誤] 無法獲取 IP 地址。請確保虛擬機正在運作且已安裝 VMware Tools。")
            sys.exit(1)
        sys.exit(0)
        
    elif args.command == "run":
        # 建立 SSH 連線並執行
        client = get_ssh_client(config, vm_manager)
        try:
            exit_code = client.execute_command(args.cmd)
            sys.exit(exit_code)
        finally:
            client.close()
            
    elif args.command == "ssh":
        # 建立 SSH 連線並啟動互動式 Terminal
        client = get_ssh_client(config, vm_manager)
        try:
            client.interactive_shell()
        finally:
            client.close()

    elif args.command == "socket-send":
        handle_socket_send(args, config)

    elif args.command == "bg-run":
        handle_bg_run(args, config, vm_manager)


if __name__ == "__main__":
    main()
