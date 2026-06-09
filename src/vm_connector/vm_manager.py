import os
import sys
import platform
import subprocess
import shutil
import time

# 定義抽象基礎類別，確保所有驅動提供一致的介面
class BaseVMManager:
    def start(self) -> bool:
        raise NotImplementedError

    def stop(self, force: bool = False) -> bool:
        raise NotImplementedError

    def get_status(self) -> str:
        """返回 'running', 'stopped' 或 'unknown'"""
        raise NotImplementedError

    def get_ip(self) -> str:
        """獲取虛擬機的 IP 位址，若無法獲取則返回 None"""
        raise NotImplementedError


class NoneVMManager(BaseVMManager):
    """純 SSH 模式，不控制虛擬機電源生命週期"""
    def start(self) -> bool:
        print("[資訊] 純 SSH 模式：跳過開機步驟。")
        return True

    def stop(self, force: bool = False) -> bool:
        print("[資訊] 純 SSH 模式：跳過關機步驟。")
        return True

    def get_status(self) -> str:
        return "unknown"

    def get_ip(self) -> str:
        return None


class LocalVMManager(BaseVMManager):
    """使用 vmrun 控制本機 VMware Fusion / Workstation 虛擬機"""
    def __init__(self, vmx_path: str, vmrun_path: str = None, vm_type: str = "fusion"):
        self.vmx_path = os.path.abspath(vmx_path)
        self.vm_type = vm_type.lower() # 'fusion' 或 'ws' (workstation)
        
        # 決定 vmrun 類型參數
        self.type_flag = "fusion" if self.vm_type == "fusion" else "ws"
        
        # 自動偵測 vmrun 路徑
        if vmrun_path:
            self.vmrun_path = vmrun_path
        else:
            self.vmrun_path = self._detect_vmrun()

        if not self.vmrun_path:
            raise FileNotFoundError(
                "找不到 vmrun 執行檔！請在本機安裝 VMware，或在 config.yaml 中手動指定 local_vm.vmrun_path。"
            )

        if not os.path.exists(self.vmx_path):
            print(f"[警告] 找不到虛擬機設定檔 (.vmx): {self.vmx_path}。請確認設定檔路徑是否正確。")

    def _detect_vmrun(self) -> str:
        # 1. 檢查系統環境變數 PATH
        path_in_env = shutil.which("vmrun")
        if path_in_env:
            return path_in_env

        # 2. 依作業系統檢查預設路徑
        sys_platform = platform.system().lower()
        if sys_platform == "darwin": # macOS (Fusion)
            default_path = "/Applications/VMware Fusion.app/Contents/Library/vmrun"
            if os.path.exists(default_path):
                return default_path
        elif sys_platform == "windows": # Windows (Workstation)
            default_path = r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe"
            if os.path.exists(default_path):
                return default_path
        elif sys_platform == "linux": # Linux (Workstation)
            default_path = "/usr/bin/vmrun"
            if os.path.exists(default_path):
                return default_path
        return None

    def _run_command(self, args: list) -> subprocess.CompletedProcess:
        cmd = [self.vmrun_path, "-T", self.type_flag] + args
        try:
            return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        except subprocess.CalledProcessError as e:
            # 輸出詳細錯誤訊息方便除錯
            print(f"[錯誤] 執行 vmrun 失敗: {e.cmd}\n錯誤訊息: {e.stderr.strip()}", file=sys.stderr)
            raise e

    def start(self) -> bool:
        print(f"[資訊] 正在啟動本機虛擬機: {os.path.basename(self.vmx_path)} ...")
        # 本機環境下預設使用 GUI 模式啟動。若是在伺服器上執行，可改為 'nogui'
        gui_mode = "gui" if platform.system().lower() != "linux" else "nogui"
        self._run_command(["start", self.vmx_path, gui_mode])
        print("[資訊] 虛擬機啟動指令已送出。")
        return True

    def stop(self, force: bool = False) -> bool:
        mode = "hard" if force else "soft"
        print(f"[資訊] 正在關閉本機虛擬機 (模式: {mode}): {os.path.basename(self.vmx_path)} ...")
        self._run_command(["stop", self.vmx_path, mode])
        print("[資訊] 虛擬機關閉指令已送出。")
        return True

    def get_status(self) -> str:
        try:
            result = self._run_command(["list"])
            # vmrun list 第一行是 Running VMs 的總數，接下來是運作中的 VMX 絕對路徑
            lines = [line.strip() for line in result.stdout.splitlines()[1:] if line.strip()]
            
            # 標準化路徑比對
            norm_vmx = os.path.normpath(self.vmx_path).lower()
            for running_vm in lines:
                if os.path.normpath(running_vm).lower() == norm_vmx:
                    return "running"
            return "stopped"
        except Exception:
            return "unknown"

    def get_ip(self) -> str:
        print("[資訊] 正在嘗試從 VMware Tools 獲取 Guest OS IP 地址...")
        try:
            # 此指令需要虛擬機已啟動，且 Guest OS 中的 VMware Tools 正在運作
            result = self._run_command(["getGuestIPAddress", self.vmx_path])
            ip = result.stdout.strip()
            if ip:
                return ip
        except Exception:
            pass
        return None


class EsxiVMManager(BaseVMManager):
    """使用 pyVmomi (vSphere API) 控制遠端 ESXi / vCenter 虛擬機"""
    def __init__(self, host: str, port: int, username: str, password: str, vm_name: str):
        self.host = host
        self.port = port or 443
        self.username = username
        self.password = password
        self.vm_name = vm_name
        self._si = None

        # 動態匯入 pyVmomi
        try:
            from pyVim.connect import SmartConnectNoSSL, Disconnect  # type: ignore
            from pyVmomi import vim  # type: ignore
            self.SmartConnectNoSSL = SmartConnectNoSSL
            self.Disconnect = Disconnect
            self.vim = vim
        except ImportError:
            raise ImportError(
                "找不到 pyvmomi 套件！請執行 `pip install pyvmomi` 以支援 ESXi/vCenter 管理功能。"
            )

    def _connect(self):
        if not self._si:
            try:
                self._si = self.SmartConnectNoSSL(
                    host=self.host,
                    port=self.port,
                    user=self.username,
                    pwd=self.password
                )
            except Exception as e:
                print(f"[錯誤] 連線到 ESXi 主機失敗: {e}", file=sys.stderr)
                raise e
        return self._si

    def _disconnect(self):
        if self._si:
            try:
                self.Disconnect(self._si)
            except Exception:
                pass
            self._si = None

    def _get_vm(self, si):
        content = si.RetrieveContent()
        container = content.viewManager.CreateContainerView(content.rootFolder, [self.vim.VirtualMachine], True)
        for vm in container.view:
            if vm.name == self.vm_name:
                return vm
        return None

    def _wait_for_task(self, task):
        """等待 vSphere 工作執行完成"""
        task_done = False
        while not task_done:
            if task.info.state == 'success':
                return task.info.result
            if task.info.state == 'error':
                print(f"[錯誤] ESXi 工作失敗: {task.info.error.msg}", file=sys.stderr)
                task_done = True
            time.sleep(2)

    def start(self) -> bool:
        si = self._connect()
        try:
            vm = self._get_vm(si)
            if not vm:
                print(f"[錯誤] 找不到名稱為 '{self.vm_name}' 的虛擬機。", file=sys.stderr)
                return False

            if vm.runtime.powerState == self.vim.VirtualMachinePowerState.poweredOn:
                print(f"[資訊] 虛擬機 '{self.vm_name}' 已經處於開機狀態。")
                return True

            print(f"[資訊] 正在啟動遠端 ESXi 虛擬機: {self.vm_name} ...")
            task = vm.PowerOnVM_Task()
            self._wait_for_task(task)
            print("[資訊] 虛擬機啟動完成。")
            return True
        finally:
            self._disconnect()

    def stop(self, force: bool = False) -> bool:
        si = self._connect()
        try:
            vm = self._get_vm(si)
            if not vm:
                print(f"[錯誤] 找不到名稱為 '{self.vm_name}' 的虛擬機。", file=sys.stderr)
                return False

            if vm.runtime.powerState == self.vim.VirtualMachinePowerState.poweredOff:
                print(f"[資訊] 虛擬機 '{self.vm_name}' 已經處於關機狀態。")
                return True

            if force:
                print(f"[資訊] 正在強制關閉遠端 ESXi 虛擬機 (PowerOff): {self.vm_name} ...")
                task = vm.PowerOffVM_Task()
                self._wait_for_task(task)
            else:
                print(f"[資訊] 正在嘗試安全關閉遠端 ESXi 虛擬機 (Shutdown Guest): {self.vm_name} ...")
                try:
                    vm.ShutdownGuest()
                    # 關閉 Guest OS 是非同步的，且沒有 Task 物件可以等待，這裡等待其狀態變更或超時
                    timeout = 60
                    while timeout > 0:
                        # 重新連接或檢查狀態
                        if vm.runtime.powerState == self.vim.VirtualMachinePowerState.poweredOff:
                            break
                        time.sleep(2)
                        timeout -= 2
                    if timeout <= 0:
                        print("[警告] 關閉 Guest OS 超時，虛擬機仍未關閉。")
                except Exception as ex:
                    print(f"[警告] 無法安全關閉 (可能未安裝 VMware Tools)，改用強制關閉。原因: {ex}")
                    task = vm.PowerOffVM_Task()
                    self._wait_for_task(task)
            print("[資訊] 虛擬機關閉完成。")
            return True
        finally:
            self._disconnect()

    def get_status(self) -> str:
        try:
            si = self._connect()
            vm = self._get_vm(si)
            if not vm:
                return "unknown"
            state = vm.runtime.powerState
            if state == self.vim.VirtualMachinePowerState.poweredOn:
                return "running"
            elif state == self.vim.VirtualMachinePowerState.poweredOff:
                return "stopped"
            return "suspended"
        except Exception:
            return "unknown"
        finally:
            self._disconnect()

    def get_ip(self) -> str:
        try:
            si = self._connect()
            vm = self._get_vm(si)
            if not vm:
                return None
            print("[資訊] 正在獲取遠端虛擬機 IP 地址...")
            # 等待幾秒鐘以讓 IP 初始化 (若剛開機的話)
            for _ in range(5):
                ip = vm.guest.ipAddress
                if ip:
                    return ip
                time.sleep(2)
        except Exception:
            pass
        finally:
            self._disconnect()
        return None


def get_vm_manager(config: dict) -> BaseVMManager:
    """工廠函數，依設定檔切換實作類型"""
    vm_type = config.get("vmware_type", "none").lower()
    
    if vm_type == "none":
        return NoneVMManager()
    
    elif vm_type in ("fusion", "workstation"):
        local_cfg = config.get("local_vm", {})
        return LocalVMManager(
            vmx_path=local_cfg.get("vmx_path", ""),
            vmrun_path=local_cfg.get("vmrun_path", None),
            vm_type=vm_type
        )
        
    elif vm_type == "esxi":
        esxi_cfg = config.get("esxi_vm", {})
        return EsxiVMManager(
            host=esxi_cfg.get("host", ""),
            port=esxi_cfg.get("port", 443),
            username=esxi_cfg.get("username", ""),
            password=esxi_cfg.get("password", ""),
            vm_name=esxi_cfg.get("vm_name", "")
        )
        
    else:
        print(f"[警告] 未知的 vmware_type: {vm_type}，預設切換為純 SSH 模式。")
        return NoneVMManager()
