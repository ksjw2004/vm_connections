import os
import sys
import socket
import select
import signal
import platform
import paramiko

class SSHClientWrapper:
    """封裝 Paramiko 連線以及 SSH 命令執行與互動式終端機"""
    def __init__(self, host: str, port: int, username: str, ssh_config: dict):
        self.host = host
        self.port = port or 22
        self.username = username
        self.config = ssh_config
        self.client = None

    def connect(self):
        """建立 SSH 連線，支援金鑰與密碼驗證"""
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        key_path = self.config.get("key_path")
        password = self.config.get("password")
        pkey = None

        if key_path:
            key_path = os.path.expanduser(key_path)
            if os.path.exists(key_path):
                print(f"[資訊] 偵測到金鑰設定，正在載入金鑰: {key_path}")
                key_password = self.config.get("key_password") or None
                
                # 遍歷嘗試不同類型的私鑰格式
                for key_class in [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.DSSKey]:
                    try:
                        pkey = key_class.from_private_key_file(key_path, password=key_password)
                        break
                    except paramiko.PasswordRequiredException:
                        print("[錯誤] 私鑰受密碼保護，但設定檔中未提供 key_password 或密碼錯誤。", file=sys.stderr)
                        raise
                    except Exception:
                        continue
                
                if not pkey:
                    print(f"[警告] 無法將 {key_path} 載入為任何支援的私鑰格式。將嘗試使用密碼驗證。", file=sys.stderr)
            else:
                print(f"[警告] 找不到設定的金鑰路徑: {key_path}，將嘗試使用密碼驗證。")

        try:
            self.client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=password if pkey is None else None,
                pkey=pkey,
                timeout=15
            )
            print(f"[資訊] SSH 連線成功: {self.username}@{self.host}:{self.port}")
        except Exception as e:
            print(f"[錯誤] 無法建立 SSH 連線: {e}", file=sys.stderr)
            raise e

    def close(self):
        """關閉 SSH 連線"""
        if self.client:
            self.client.close()
            self.client = None

    def execute_command(self, command: str) -> int:
        """執行單一命令並即時將 stdout 與 stderr 串流輸出到控制台"""
        if not self.client:
            raise RuntimeError("SSH Client 未連線。請先呼叫 connect()")

        transport = self.client.get_transport()
        chan = transport.open_session()
        chan.exec_command(command)

        # 非阻塞讀取
        chan.settimeout(0.0)

        try:
            while True:
                # 監聽 channel 的讀取狀態
                r, _, _ = select.select([chan], [], [], 0.1)
                if chan in r:
                    # 讀取標準輸出 (stdout)
                    if chan.recv_ready():
                        data = chan.recv(4096)
                        if data:
                            sys.stdout.write(data.decode("utf-8", errors="replace"))
                            sys.stdout.flush()
                    # 讀取標準錯誤輸出 (stderr)
                    if chan.recv_stderr_ready():
                        data = chan.recv_stderr(4096)
                        if data:
                            sys.stderr.write(data.decode("utf-8", errors="replace"))
                            sys.stderr.flush()
                
                # 若 channel 已結束執行且快取已讀完
                if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                    break
        except Exception as e:
            print(f"\n[錯誤] 指令執行中斷: {e}", file=sys.stderr)
        
        exit_code = chan.recv_exit_status()
        return exit_code

    def interactive_shell(self):
        """開啟與遠端虛擬機的互動式 TTY 終端機"""
        if not self.client:
            raise RuntimeError("SSH Client 未連線。請先呼叫 connect()")

        # 獲取 transport
        transport = self.client.get_transport()
        chan = transport.open_session()

        # 獲取本機終端機大小
        try:
            cols, rows = os.get_terminal_size()
        except Exception:
            cols, rows = 80, 24

        # 請求分配虛擬終端機 (PTY)
        chan.get_pty(term="xterm-256color", width=cols, height=rows)
        chan.invoke_shell()

        # 依不同平台切換處理方式
        if platform.system().lower() == "windows":
            self._windows_shell_loop(chan)
        else:
            self._posix_shell_loop(chan)

    def _posix_shell_loop(self, chan):
        """macOS 與 Linux 下的互動式終端機循環 (支援 Raw Mode 與視窗重繪)"""
        import termios
        import tty

        # 儲存本機終端機原先的屬性設定
        old_tty = termios.tcgetattr(sys.stdin)

        # 定義視窗大小變更 (SIGWINCH) 監聽器
        def handle_resize(signum, frame):
            try:
                c, r = os.get_terminal_size()
                chan.resize_pty(width=c, height=r)
            except Exception:
                pass

        # 註冊信號
        old_handler = signal.signal(signal.SIGWINCH, handle_resize)

        try:
            # 切換本機輸入為 Raw Mode，將按鍵直接傳送不作本機行快取
            tty.setraw(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
            chan.settimeout(0.0)

            print("\r\n--- 互動式終端機已建立，按 Ctrl+D 或輸入 exit 結束連線 ---\r\n")

            while True:
                # 監聽本機標準輸入與 SSH 連線頻道
                read_ready, _, _ = select.select([chan, sys.stdin], [], [])
                
                if chan in read_ready:
                    try:
                        data = chan.recv(4096)
                        if not data:
                            break
                        sys.stdout.write(data.decode("utf-8", errors="replace"))
                        sys.stdout.flush()
                    except socket.timeout:
                        pass
                
                if sys.stdin in read_ready:
                    # 讀取本機鍵盤輸入並送往 SSH 頻道
                    data = os.read(sys.stdin.fileno(), 4096)
                    if not data:
                        break
                    chan.send(data)
        except Exception:
            # 確保發生例外時能正常復原終端機
            pass
        finally:
            # 復原終端機設定
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty)
            # 復原信號處理
            signal.signal(signal.SIGWINCH, old_handler)
            print("\r\n--- 互動式終端機已關閉 ---\r\n")

    def _windows_shell_loop(self, chan):
        """Windows 的簡易互動式終端機循環 (不支援 raw terminal)"""
        import threading

        def recv_loop():
            try:
                while True:
                    data = chan.recv(256)
                    if not data:
                        break
                    sys.stdout.write(data.decode("utf-8", errors="replace"))
                    sys.stdout.flush()
            except Exception:
                pass

        # 開啟讀取執行緒
        t = threading.Thread(target=recv_loop, daemon=True)
        t.start()

        print("\n--- 互動式終端機已建立 (Windows 模式)，輸入 exit 結束連線 ---\n")
        try:
            while t.is_alive():
                # 每次讀取一個字元傳送，注意 Windows 終端機按 Enter 會產生 \r\n
                line = sys.stdin.readline()
                if not line:
                    break
                chan.send(line)
        except Exception:
            pass
