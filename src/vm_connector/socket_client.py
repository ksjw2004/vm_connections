import json
import socket
import sys


class SocketClient:
    """
    TCP Socket Client，用於連線到 VMware VM 內部執行的 Socket Server 並傳送資料。
    支援 with 語法（context manager）自動管理連線。
    """

    def __init__(self, host: str, port: int, timeout: int = 10, encoding: str = "utf-8"):
        """
        初始化 Socket Client。

        Args:
            host:     VM 的 IP 位址
            port:     VM 內 Socket Server 監聽的 Port
            timeout:  連線逾時秒數（預設 10 秒）
            encoding: 文字資料編碼（預設 utf-8）
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.encoding = encoding
        self._sock: socket.socket | None = None

    # ------------------------------------------------------------------
    # 連線管理
    # ------------------------------------------------------------------

    def connect(self):
        """建立 TCP 連線到遠端 Socket Server。"""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect((self.host, self.port))
            print(f"[資訊] Socket 連線成功: {self.host}:{self.port}")
        except ConnectionRefusedError:
            print(
                f"[錯誤] 連線被拒絕 ({self.host}:{self.port})。"
                f"請確認 VM 內的 Socket Server 已啟動並監聽該 Port。",
                file=sys.stderr,
            )
            raise
        except socket.timeout:
            print(
                f"[錯誤] 連線逾時 ({self.timeout} 秒)。"
                f"請確認 VM IP 正確且防火牆未封鎖 Port {self.port}。",
                file=sys.stderr,
            )
            raise
        except OSError as e:
            print(f"[錯誤] 無法建立 Socket 連線: {e}", file=sys.stderr)
            raise

    def close(self):
        """關閉 Socket 連線。"""
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            finally:
                self._sock = None
                print("[資訊] Socket 連線已關閉。")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    # ------------------------------------------------------------------
    # 傳送方法
    # ------------------------------------------------------------------

    def send_bytes(self, data: bytes) -> int:
        """
        傳送原始二進位資料。

        Args:
            data: 要傳送的 bytes

        Returns:
            實際傳送的位元組數
        """
        if not self._sock:
            raise RuntimeError("Socket 未連線，請先呼叫 connect()。")
        try:
            self._sock.sendall(data)
            sent = len(data)
            print(f"[資訊] 已傳送 {sent} bytes。")
            return sent
        except socket.timeout:
            print("[錯誤] 傳送資料時逾時。", file=sys.stderr)
            raise
        except OSError as e:
            print(f"[錯誤] 傳送資料失敗: {e}", file=sys.stderr)
            raise

    def send_text(self, message: str) -> int:
        """
        傳送 UTF-8（或指定編碼）文字訊息。

        Args:
            message: 要傳送的文字字串

        Returns:
            實際傳送的位元組數
        """
        encoded = message.encode(self.encoding)
        print(f"[資訊] 傳送文字: {message!r}")
        return self.send_bytes(encoded)

    def send_json(self, data: dict | list) -> int:
        """
        將 Python dict 或 list 序列化為 JSON 字串後傳送。

        Args:
            data: 要序列化並傳送的 Python 物件

        Returns:
            實際傳送的位元組數
        """
        json_str = json.dumps(data, ensure_ascii=False)
        print(f"[資訊] 傳送 JSON: {json_str}")
        return self.send_text(json_str)

    # ------------------------------------------------------------------
    # 接收方法（可選）
    # ------------------------------------------------------------------

    def receive(self, size: int = 4096) -> bytes:
        """
        從 Server 接收回傳資料（最多 size bytes）。

        Args:
            size: 最大接收位元組數（預設 4096）

        Returns:
            接收到的 bytes；若連線已關閉則回傳 b""
        """
        if not self._sock:
            raise RuntimeError("Socket 未連線，請先呼叫 connect()。")
        try:
            data = self._sock.recv(size)
            if data:
                print(f"[資訊] 收到 {len(data)} bytes 回應。")
            return data
        except socket.timeout:
            print("[警告] 等待回應逾時，Server 可能未回傳任何資料。", file=sys.stderr)
            return b""
        except OSError as e:
            print(f"[錯誤] 接收資料失敗: {e}", file=sys.stderr)
            raise

    def receive_text(self, size: int = 4096) -> str:
        """
        接收並解碼回傳的文字資料。

        Args:
            size: 最大接收位元組數（預設 4096）

        Returns:
            解碼後的文字字串
        """
        data = self.receive(size)
        return data.decode(self.encoding, errors="replace")
