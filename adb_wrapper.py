"""
GrapheneOS Cloner - ADB/Fastboot Wrapper
Handles all communication with Android devices via adb and fastboot.
All subprocess calls are silent (no terminal windows).
"""
import subprocess
import os
import re
import time
import threading
from typing import List, Optional, Dict, Tuple, Callable

from config import get_adb_path, get_fastboot_path

# Subprocess creation flags for Windows (hide console window)
CREATE_NO_WINDOW = 0x08000000


def _run(cmd: List[str], timeout: int = 60) -> Tuple[int, str, str]:
    """Run a command silently and return (returncode, stdout, stderr)."""
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": timeout,
    }
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si

    try:
        proc = subprocess.run(cmd, **kwargs)
        return proc.returncode, proc.stdout.decode("utf-8", errors="replace"), proc.stderr.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", f"Binary not found: {cmd[0]}"


def _run_stream(cmd: List[str], progress_callback: Optional[Callable] = None, timeout: int = 3600) -> Tuple[int, str]:
    """Run a command and stream output line-by-line for progress tracking."""
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "bufsize": 1,
        "universal_newlines": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kwargs["startupinfo"] = si

    try:
        proc = subprocess.Popen(cmd, **kwargs)
        output_lines = []
        for line in proc.stdout:
            line = line.strip()
            output_lines.append(line)
            if progress_callback:
                progress_callback(line)
        proc.wait(timeout=timeout)
        return proc.returncode, "\n".join(output_lines)
    except subprocess.TimeoutExpired:
        proc.kill()
        return -1, "Command timed out"
    except FileNotFoundError:
        return -1, f"Binary not found: {cmd[0]}"


class ADBDevice:
    """Represents a connected Android device."""

    def __init__(self, serial: str, state: str, model: str = "", product: str = ""):
        self.serial = serial
        self.state = state
        self.model = model
        self.product = product

    def __repr__(self):
        return f"ADBDevice({self.serial}, {self.state}, {self.model})"


class ADBWrapper:
    """Wrapper around adb binary."""

    def __init__(self, adb_path: Optional[str] = None):
        self.adb = adb_path or get_adb_path()

    def start_server(self) -> bool:
        rc, out, err = _run([self.adb, "start-server"])
        return rc == 0

    def kill_server(self) -> bool:
        rc, out, err = _run([self.adb, "kill-server"])
        return rc == 0

    def list_devices(self) -> List[ADBDevice]:
        """List all connected ADB devices."""
        rc, out, err = _run([self.adb, "devices", "-l"])
        if rc != 0:
            return []

        devices = []
        for line in out.strip().split("\n")[1:]:  # Skip header
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial = parts[0]
            state = parts[1]
            model = ""
            product = ""
            for p in parts[2:]:
                if p.startswith("model:"):
                    model = p.split(":", 1)[1]
                elif p.startswith("product:"):
                    product = p.split(":", 1)[1]
            devices.append(ADBDevice(serial, state, model, product))
        return devices

    def get_device_info(self, serial: str) -> Dict[str, str]:
        """Get detailed device info via adb shell getprop."""
        info = {}
        props = [
            ("ro.product.model", "model"),
            ("ro.product.device", "device"),
            ("ro.build.display.id", "build"),
            ("ro.build.version.release", "android_version"),
            ("ro.serialno", "serial"),
            ("ro.product.brand", "brand"),
        ]
        for prop, key in props:
            rc, out, err = _run([self.adb, "-s", serial, "shell", "getprop", prop])
            if rc == 0:
                info[key] = out.strip()
        return info

    def get_installed_packages(self, serial: str) -> List[str]:
        """Get list of installed packages (user + system)."""
        rc, out, err = _run([self.adb, "-s", serial, "shell", "pm", "list", "packages", "-f"])
        if rc != 0:
            return []
        packages = []
        for line in out.strip().split("\n"):
            line = line.strip()
            if line.startswith("package:"):
                # Format: package:/path/to/apk=com.example.app
                match = re.match(r"package:(.+?)=(.+)", line)
                if match:
                    packages.append(match.group(2))
        return sorted(packages)

    def get_user_packages(self, serial: str, user_id: int = 0) -> List[str]:
        """Get list of user-installed packages only (third-party).
        Optionally specify a user_id for multi-user devices."""
        cmd = [self.adb, "-s", serial, "shell", "pm", "list", "packages",
               "--user", str(user_id), "-3"]
        rc, out, err = _run(cmd)
        if rc != 0:
            return []
        packages = []
        for line in out.strip().split("\n"):
            line = line.strip()
            if line.startswith("package:"):
                pkg = line.replace("package:", "").strip()
                packages.append(pkg)
        return sorted(packages)

    def list_users(self, serial: str) -> List[Dict[str, str]]:
        """List all user profiles on the device.
        Returns list of dicts with 'id' and 'name' keys."""
        rc, out, err = _run([self.adb, "-s", serial, "shell", "pm", "list", "users"])
        if rc != 0:
            return [{"id": "0", "name": "Owner"}]
        users = []
        for line in out.strip().split("\n"):
            # Format: UserInfo{0:Owner:c13} running
            match = re.search(r'UserInfo\{(\d+):([^:}]+)', line)
            if match:
                users.append({"id": match.group(1), "name": match.group(2)})
        return users if users else [{"id": "0", "name": "Owner"}]

    def backup_app_for_user(self, serial: str, package: str, user_id: int,
                            output_path: str) -> bool:
        """Backup a single app's APK for a specific user profile.
        APKs are shared across users, so this gets the APK path for the given user."""
        rc, out, err = _run([self.adb, "-s", serial, "shell",
                             "pm", "path", "--user", str(user_id), package])
        if rc != 0 or not out.strip():
            return False
        apk_path = out.strip().replace("package:", "").split("\n")[0].strip()
        if not apk_path:
            return False
        return self.pull_file(serial, apk_path, output_path)

    def pull_file(self, serial: str, remote: str, local: str) -> bool:
        """Pull a file from device to local."""
        rc, out, err = _run([self.adb, "-s", serial, "pull", remote, local], timeout=300)
        return rc == 0

    def push_file(self, serial: str, local: str, remote: str) -> bool:
        """Push a file from local to device."""
        rc, out, err = _run([self.adb, "-s", serial, "push", local, remote], timeout=300)
        return rc == 0

    def shell(self, serial: str, command: str, timeout: int = 60) -> Tuple[int, str]:
        """Run a shell command on device."""
        rc, out, err = _run([self.adb, "-s", serial, "shell", command], timeout=timeout)
        return rc, out

    def reboot(self, serial: str, mode: str = "") -> bool:
        """Reboot device. mode can be '', 'bootloader', 'recovery'."""
        cmd = [self.adb, "-s", serial, "reboot"]
        if mode:
            cmd.append(mode)
        rc, out, err = _run(cmd, timeout=30)
        return rc == 0

    def reboot_to_bootloader(self, serial: str) -> bool:
        """Reboot device into fastboot/bootloader mode."""
        return self.reboot(serial, "bootloader")

    def backup_app(self, serial: str, package: str, output_path: str) -> bool:
        """Backup a single app's APK."""
        # Get APK path
        rc, out = self.shell(serial, f"pm path {package}")
        if rc != 0:
            return False
        apk_path = out.strip().replace("package:", "")
        if not apk_path:
            return False
        return self.pull_file(serial, apk_path, output_path)

    def install_apk(self, serial: str, apk_path: str) -> bool:
        """Install an APK on device."""
        rc, out, err = _run([self.adb, "-s", serial, "install", "-r", apk_path], timeout=120)
        return rc == 0 and "Success" in out

    def install_apk_for_user(self, serial: str, apk_path: str, user_id: int) -> bool:
        """Install an APK for a specific user profile."""
        rc, out, err = _run(
            [self.adb, "-s", serial, "install", "-r", "--user", str(user_id), apk_path],
            timeout=120
        )
        return rc == 0 and "Success" in out

    def get_settings(self, serial: str, namespace: str,
                     user_id: Optional[int] = None) -> Dict[str, str]:
        """Get all settings from a namespace (system, secure, global).
        Returns dict of key=value pairs.
        Per-user settings supported for 'system' and 'secure' namespaces."""
        cmd = [self.adb, "-s", serial, "shell", "settings", "list", namespace]
        if user_id is not None and namespace in ("system", "secure"):
            cmd = [self.adb, "-s", serial, "shell", "settings",
                   "--user", str(user_id), "list", namespace]
        rc, out, err = _run(cmd, timeout=30)
        if rc != 0:
            return {}
        settings = {}
        for line in out.strip().split("\n"):
            line = line.strip()
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                if key:
                    settings[key] = value.strip()
        return settings

    def put_setting(self, serial: str, namespace: str, key: str, value: str,
                    user_id: Optional[int] = None) -> bool:
        """Set a single setting value.
        Per-user settings supported for 'system' and 'secure' namespaces."""
        cmd = [self.adb, "-s", serial, "shell", "settings", "put", namespace, key, value]
        if user_id is not None and namespace in ("system", "secure"):
            cmd = [self.adb, "-s", serial, "shell", "settings",
                   "--user", str(user_id), "put", namespace, key, value]
        rc, out, err = _run(cmd, timeout=10)
        return rc == 0

    def get_granted_permissions(self, serial: str, package: str,
                                user_id: int = 0) -> List[str]:
        """Get list of runtime permissions granted to an app."""
        rc, out = self.shell(serial,
                             f"dumpsys package {package} | grep 'granted=true'")
        if rc != 0:
            return []
        perms = []
        for line in out.strip().split("\n"):
            line = line.strip()
            # Format: android.permission.CAMERA: granted=true
            if "granted=true" in line:
                perm = line.split(":")[0].strip()
                if perm.startswith("android.permission.") or perm.startswith("com."):
                    perms.append(perm)
        return perms

    def grant_permission(self, serial: str, package: str, permission: str,
                         user_id: int = 0) -> bool:
        """Grant a runtime permission to an app."""
        cmd = f"pm grant --user {user_id} {package} {permission}"
        rc, out = self.shell(serial, cmd)
        return rc == 0

    def wait_for_device(self, serial: str, timeout: int = 60) -> bool:
        """Wait for device to come online."""
        rc, out, err = _run([self.adb, "-s", serial, "wait-for-device"], timeout=timeout)
        return rc == 0

    def enable_root(self, serial: str) -> bool:
        """Enable ADB root access (requires root enabled in Developer Options on GrapheneOS)."""
        rc, out, err = _run([self.adb, "-s", serial, "root"], timeout=15)
        if rc == 0:
            time.sleep(2)  # Wait for adb to reconnect after root
            return True
        return False

    def is_root(self, serial: str) -> bool:
        """Check if ADB is running as root."""
        rc, out = self.shell(serial, "id")
        return rc == 0 and "uid=0" in out

    def get_partition_path(self, serial: str, partition: str) -> Optional[str]:
        """Find the block device path for a partition name."""
        # Try by-name symlink first (most common on Pixel devices)
        for prefix in ["/dev/block/by-name/", "/dev/block/platform/*/by-name/",
                       "/dev/block/bootdevice/by-name/"]:
            rc, out = self.shell(serial, f"ls {prefix}{partition} 2>/dev/null")
            if rc == 0 and out.strip():
                return out.strip()

        # Try reading from /dev/block/by-name with slot suffix (A/B devices)
        for suffix in ["_a", "_b"]:
            rc, out = self.shell(serial, f"ls /dev/block/by-name/{partition}{suffix} 2>/dev/null")
            if rc == 0 and out.strip():
                return out.strip()

        return None

    def dump_partition(self, serial: str, partition: str, output_path: str,
                       progress_callback: Optional[Callable] = None) -> bool:
        """Dump a partition using ADB with dd. Requires root access.
        This is the most reliable method for reading partitions.
        """
        block_path = self.get_partition_path(serial, partition)
        if not block_path:
            # Fallback: try direct path
            block_path = f"/dev/block/by-name/{partition}"

        if progress_callback:
            progress_callback(f"Reading {partition} from {block_path}...")

        # Get partition size first
        rc, size_out = self.shell(serial, f"blockdev --getsize64 {block_path} 2>/dev/null")
        total_bytes = int(size_out.strip()) if rc == 0 and size_out.strip().isdigit() else 0

        # Use adb exec-out with dd to stream partition data to local file
        cmd = [self.adb, "-s", serial, "exec-out",
               "dd", f"if={block_path}", "bs=4194304"]  # 4MB blocks

        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if os.name == "nt":
            kwargs["creationflags"] = CREATE_NO_WINDOW
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            kwargs["startupinfo"] = si

        try:
            proc = subprocess.Popen(cmd, **kwargs)
            bytes_written = 0
            block_size = 4194304  # 4MB

            with open(output_path, "wb") as f:
                while True:
                    data = proc.stdout.read(block_size)
                    if not data:
                        break
                    f.write(data)
                    bytes_written += len(data)

                    if progress_callback and total_bytes > 0:
                        pct = min(100, int(bytes_written * 100 / total_bytes))
                        progress_callback(f"{partition}: {bytes_written // 1048576}MB / {total_bytes // 1048576}MB ({pct}%)")
                    elif progress_callback:
                        progress_callback(f"{partition}: {bytes_written // 1048576}MB written")

            proc.wait(timeout=30)

            # Verify we got actual data
            if bytes_written == 0:
                if progress_callback:
                    progress_callback(f"WARNING: No data read from {partition}")
                return False

            if progress_callback:
                progress_callback(f"{partition}: Done ({bytes_written // 1048576}MB)")
            return True

        except Exception as e:
            if progress_callback:
                progress_callback(f"ERROR dumping {partition}: {str(e)}")
            return False

    def get_user_packages(self, serial: str) -> List[str]:
        """Get list of user-installed packages."""
        return self.get_installed_packages(serial)


class FastbootWrapper:
    """Wrapper around fastboot binary."""

    def __init__(self, fastboot_path: Optional[str] = None):
        self.fastboot = fastboot_path or get_fastboot_path()

    def list_devices(self) -> List[Dict[str, str]]:
        """List all devices in fastboot mode."""
        rc, out, err = _run([self.fastboot, "devices", "-l"])
        if rc != 0:
            return []

        devices = []
        for line in out.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                devices.append({
                    "serial": parts[0],
                    "state": parts[1] if len(parts) > 1 else "fastboot",
                })
        return devices

    def get_var(self, serial: str, var: str) -> Optional[str]:
        """Get a fastboot variable."""
        rc, out, err = _run([self.fastboot, "-s", serial, "getvar", var], timeout=10)
        # fastboot getvar outputs to stderr
        combined = out + err
        for line in combined.split("\n"):
            if line.startswith(f"{var}:"):
                return line.split(":", 1)[1].strip()
        return None

    def get_device_info(self, serial: str) -> Dict[str, str]:
        """Get device info from fastboot variables."""
        info = {}
        for var in ["product", "serialno", "variant", "secure", "unlocked"]:
            val = self.get_var(serial, var)
            if val:
                info[var] = val
        return info

    def wait_for_device(self, serial: str, timeout: int = 30) -> bool:
        """Wait for a specific device to appear in fastboot mode."""
        start = time.time()
        while time.time() - start < timeout:
            devices = self.list_devices()
            for d in devices:
                if d["serial"] == serial:
                    return True
            time.sleep(2)
        # Also accept if ANY device is in fastboot (serial may change)
        devices = self.list_devices()
        return len(devices) > 0

    def flash_partition(self, serial: str, partition: str, image_path: str,
                        progress_callback: Optional[Callable] = None) -> bool:
        """Flash an image to a partition."""
        cmd = [self.fastboot, "-s", serial, "flash", partition, image_path]
        rc, output = _run_stream(cmd, progress_callback, timeout=1800)
        return rc == 0

    def erase_partition(self, serial: str, partition: str) -> bool:
        """Erase a partition."""
        rc, out, err = _run([self.fastboot, "-s", serial, "erase", partition], timeout=60)
        return rc == 0

    def reboot(self, serial: str) -> bool:
        """Reboot device from fastboot mode."""
        rc, out, err = _run([self.fastboot, "-s", serial, "reboot"], timeout=30)
        return rc == 0

    def reboot_to_bootloader(self, serial: str) -> bool:
        """Reboot to bootloader from fastboot mode."""
        rc, out, err = _run([self.fastboot, "-s", serial, "reboot-bootloader"], timeout=30)
        return rc == 0

    def oem_unlock(self, serial: str) -> Tuple[bool, str]:
        """Unlock the bootloader (OEM unlock)."""
        rc, out, err = _run([self.fastboot, "-s", serial, "flashing", "unlock"], timeout=60)
        return rc == 0, out + err

    def oem_lock(self, serial: str) -> Tuple[bool, str]:
        """Lock the bootloader (OEM lock)."""
        rc, out, err = _run([self.fastboot, "-s", serial, "flashing", "lock"], timeout=60)
        return rc == 0, out + err

    def fetch_partition(self, serial: str, partition: str, output_path: str,
                        progress_callback: Optional[Callable] = None) -> bool:
        """Fetch (dump) a partition image from device.
        Uses 'fastboot fetch' which is available in newer platform-tools.
        """
        cmd = [self.fastboot, "-s", serial, "fetch", partition, output_path]
        rc, output = _run_stream(cmd, progress_callback, timeout=300)
        return rc == 0

    def set_active_slot(self, serial: str, slot: str = "a") -> bool:
        """Set the active slot (A/B devices)."""
        rc, out, err = _run([self.fastboot, "-s", serial, "set_active", slot], timeout=10)
        return rc == 0

    def flash_raw(self, serial: str, partition: str, image_path: str) -> bool:
        """Flash a raw image without formatting."""
        rc, out, err = _run([self.fastboot, "-s", serial, "flash", partition, image_path], timeout=1800)
        return rc == 0

    def update(self, serial: str, image_zip_path: str, wipe: bool = True,
               progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """Flash using 'fastboot update' which handles A/B slots correctly.
        This is the proper way to flash factory images on A/B devices like Pixel.
        Args:
            serial: Device serial
            image_zip_path: Path to the image ZIP (inner archive from factory image)
            wipe: If True, adds -w flag to erase userdata
        """
        cmd = [self.fastboot, "-s", serial]
        if wipe:
            cmd.append("-w")
        cmd.extend(["update", image_zip_path])
        rc, output = _run_stream(cmd, progress_callback, timeout=1800)
        return rc == 0, output
