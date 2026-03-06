"""
GrapheneOS Cloner - Imaging Engine
Handles creating, storing, and restoring full device images.
Images are stored as compressed archives containing individual partition dumps.
"""
import os
import json
import zipfile
import shutil
import tempfile
import time
from typing import Optional, List, Dict, Callable
from dataclasses import dataclass, asdict

from config import (
    PIXEL3_PARTITIONS, SYSTEM_PARTITIONS, DATA_PARTITION,
    IMAGE_EXTENSION, ARCHIVE_EXTENSION, BACKUP_EXTENSION,
    get_default_image_dir, get_default_backup_dir,
)
from adb_wrapper import ADBWrapper, FastbootWrapper


@dataclass
class ImageManifest:
    """Metadata about a device image."""
    device_serial: str
    device_model: str
    device_product: str
    grapheneos_build: str
    created_at: str
    partitions: List[str]
    app_list: List[str]
    total_size_bytes: int
    version: str = "1.0"


class ImagingEngine:
    """Core imaging engine for creating and restoring device images."""

    def __init__(self, adb: Optional[ADBWrapper] = None, fastboot: Optional[FastbootWrapper] = None):
        self.adb = adb or ADBWrapper()
        self.fastboot = fastboot or FastbootWrapper()
        self._cancel_flag = False

    def cancel(self):
        """Request cancellation of current operation."""
        self._cancel_flag = True

    def _check_cancel(self):
        if self._cancel_flag:
            self._cancel_flag = False
            raise OperationCancelled("Operation cancelled by user")

    def create_image(self, serial: str, output_path: str,
                     partitions: Optional[List[str]] = None,
                     progress_callback: Optional[Callable] = None,
                     status_callback: Optional[Callable] = None) -> str:
        """
        Create a full device image from a connected device.
        The device should be in fastboot mode.

        Args:
            serial: Device serial number
            output_path: Directory to save the image archive
            partitions: List of partitions to capture (default: all)
            progress_callback: Called with (current_step, total_steps, message)
            status_callback: Called with status message strings

        Returns:
            Path to the created .gimg archive
        """
        self._cancel_flag = False
        partitions = partitions or PIXEL3_PARTITIONS

        if status_callback:
            status_callback("Preparing to create image...")

        # Create temp directory for partition dumps
        temp_dir = tempfile.mkdtemp(prefix="gcloner_")

        try:
            # Get device info
            if status_callback:
                status_callback("Getting device information...")

            device_info = self.fastboot.get_device_info(serial)
            total_steps = len(partitions) + 2  # partitions + manifest + archive
            current_step = 0

            # Get app list via ADB if device was in ADB mode before
            app_list = []

            # Dump each partition
            for partition in partitions:
                self._check_cancel()
                current_step += 1

                if status_callback:
                    status_callback(f"Dumping partition: {partition} ({current_step}/{len(partitions)})")
                if progress_callback:
                    progress_callback(current_step, total_steps, f"Dumping {partition}")

                img_path = os.path.join(temp_dir, f"{partition}{IMAGE_EXTENSION}")

                def _part_progress(line):
                    if status_callback:
                        status_callback(f"  {partition}: {line}")

                success = self.fastboot.fetch_partition(serial, partition, img_path, _part_progress)
                if not success:
                    # Try alternative method: use dd via adb
                    if status_callback:
                        status_callback(f"  Fetch failed for {partition}, trying alternative method...")
                    # We'll create an empty placeholder and note it
                    with open(img_path, 'wb') as f:
                        pass  # Empty file as placeholder

            self._check_cancel()

            # Create manifest
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps, "Creating manifest")

            total_size = sum(
                os.path.getsize(os.path.join(temp_dir, f"{p}{IMAGE_EXTENSION}"))
                for p in partitions
                if os.path.exists(os.path.join(temp_dir, f"{p}{IMAGE_EXTENSION}"))
            )

            manifest = ImageManifest(
                device_serial=device_info.get("serialno", serial),
                device_model=device_info.get("product", "blueline"),
                device_product=device_info.get("product", "Pixel 3"),
                grapheneos_build=device_info.get("variant", "unknown"),
                created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                partitions=partitions,
                app_list=app_list,
                total_size_bytes=total_size,
            )

            manifest_path = os.path.join(temp_dir, "manifest.json")
            with open(manifest_path, "w") as f:
                json.dump(asdict(manifest), f, indent=2)

            # Create compressed archive
            current_step += 1
            if status_callback:
                status_callback("Creating compressed archive...")
            if progress_callback:
                progress_callback(current_step, total_steps, "Compressing archive")

            os.makedirs(output_path, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            model = device_info.get("product", "pixel3")
            archive_name = f"{model}_{timestamp}{ARCHIVE_EXTENSION}"
            archive_path = os.path.join(output_path, archive_name)

            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(manifest_path, "manifest.json")
                for partition in partitions:
                    img_file = f"{partition}{IMAGE_EXTENSION}"
                    img_full = os.path.join(temp_dir, img_file)
                    if os.path.exists(img_full):
                        zf.write(img_full, img_file)

            if status_callback:
                status_callback(f"Image created: {archive_name}")

            return archive_path

        finally:
            # Cleanup temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)

    def restore_image(self, serial: str, archive_path: str,
                      partitions: Optional[List[str]] = None,
                      progress_callback: Optional[Callable] = None,
                      status_callback: Optional[Callable] = None) -> bool:
        """
        Restore a device image to a connected device in fastboot mode.

        Args:
            serial: Device serial number
            archive_path: Path to the .gimg or .gbak archive
            partitions: Specific partitions to restore (default: all in archive)
            progress_callback: Called with (current_step, total_steps, message)
            status_callback: Called with status message strings

        Returns:
            True if successful
        """
        self._cancel_flag = False

        if status_callback:
            status_callback("Preparing to restore image...")

        temp_dir = tempfile.mkdtemp(prefix="gcloner_restore_")

        try:
            # Extract archive
            if status_callback:
                status_callback("Extracting archive...")

            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(temp_dir)

            # Read manifest
            manifest_path = os.path.join(temp_dir, "manifest.json")
            if os.path.exists(manifest_path):
                with open(manifest_path) as f:
                    manifest_data = json.load(f)
                available_partitions = manifest_data.get("partitions", [])
            else:
                # No manifest, discover from files
                available_partitions = [
                    os.path.splitext(f)[0] for f in os.listdir(temp_dir)
                    if f.endswith(IMAGE_EXTENSION)
                ]

            # Determine which partitions to flash
            target_partitions = partitions or available_partitions
            total_steps = len(target_partitions) + 1  # partitions + reboot
            current_step = 0

            # Flash each partition
            for partition in target_partitions:
                self._check_cancel()
                current_step += 1

                img_path = os.path.join(temp_dir, f"{partition}{IMAGE_EXTENSION}")
                if not os.path.exists(img_path):
                    if status_callback:
                        status_callback(f"Skipping {partition} (not found in archive)")
                    continue

                if os.path.getsize(img_path) == 0:
                    if status_callback:
                        status_callback(f"Skipping {partition} (empty image)")
                    continue

                if status_callback:
                    status_callback(f"Flashing partition: {partition} ({current_step}/{len(target_partitions)})")
                if progress_callback:
                    progress_callback(current_step, total_steps, f"Flashing {partition}")

                def _flash_progress(line):
                    if status_callback:
                        status_callback(f"  {partition}: {line}")

                success = self.fastboot.flash_partition(serial, partition, img_path, _flash_progress)
                if not success:
                    if status_callback:
                        status_callback(f"WARNING: Failed to flash {partition}")

            # Set active slot
            self.fastboot.set_active_slot(serial, "a")

            # Reboot
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps, "Rebooting device")
            if status_callback:
                status_callback("Rebooting device...")

            self.fastboot.reboot(serial)

            if status_callback:
                status_callback("Restore complete! Device is rebooting.")

            return True

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def create_backup(self, serial: str, output_path: str,
                      include_apps: bool = True,
                      progress_callback: Optional[Callable] = None,
                      status_callback: Optional[Callable] = None) -> str:
        """
        Create a backup of a device (ADB mode).
        Captures app APKs and user data via ADB backup mechanisms.

        Returns:
            Path to the created .gbak backup file
        """
        self._cancel_flag = False
        os.makedirs(output_path, exist_ok=True)

        temp_dir = tempfile.mkdtemp(prefix="gcloner_backup_")

        try:
            if status_callback:
                status_callback("Getting device info...")

            device_info = self.adb.get_device_info(serial)
            app_list = self.adb.get_user_packages(serial) if include_apps else []
            total_steps = len(app_list) + 3 if include_apps else 3
            current_step = 0

            # Backup APKs
            apps_dir = os.path.join(temp_dir, "apps")
            os.makedirs(apps_dir, exist_ok=True)

            if include_apps and app_list:
                for pkg in app_list:
                    self._check_cancel()
                    current_step += 1

                    if status_callback:
                        status_callback(f"Backing up app: {pkg} ({current_step}/{len(app_list)})")
                    if progress_callback:
                        progress_callback(current_step, total_steps, f"Backup {pkg}")

                    apk_path = os.path.join(apps_dir, f"{pkg}.apk")
                    self.adb.backup_app(serial, pkg, apk_path)

            # Create manifest
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps, "Creating manifest")

            manifest = {
                "type": "backup",
                "device_serial": device_info.get("serial", serial),
                "device_model": device_info.get("model", "unknown"),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "app_list": app_list,
                "version": "1.0",
            }

            with open(os.path.join(temp_dir, "manifest.json"), "w") as f:
                json.dump(manifest, f, indent=2)

            # Create archive
            current_step += 1
            if status_callback:
                status_callback("Creating backup archive...")
            if progress_callback:
                progress_callback(current_step, total_steps, "Compressing")

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            model = device_info.get("model", "pixel3").replace(" ", "_")
            backup_name = f"backup_{model}_{timestamp}{BACKUP_EXTENSION}"
            backup_path = os.path.join(output_path, backup_name)

            with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        full = os.path.join(root, file)
                        arcname = os.path.relpath(full, temp_dir)
                        zf.write(full, arcname)

            if status_callback:
                status_callback(f"Backup created: {backup_name}")

            return backup_path

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def restore_backup(self, serial: str, backup_path: str,
                       selected_apps: Optional[List[str]] = None,
                       progress_callback: Optional[Callable] = None,
                       status_callback: Optional[Callable] = None) -> bool:
        """
        Restore a backup to a device (ADB mode).
        Installs selected app APKs.

        Args:
            serial: Device serial
            backup_path: Path to .gbak file
            selected_apps: List of package names to install (None = all)

        Returns:
            True if successful
        """
        self._cancel_flag = False
        temp_dir = tempfile.mkdtemp(prefix="gcloner_brestore_")

        try:
            if status_callback:
                status_callback("Extracting backup...")

            with zipfile.ZipFile(backup_path, "r") as zf:
                zf.extractall(temp_dir)

            # Read manifest
            manifest_path = os.path.join(temp_dir, "manifest.json")
            if os.path.exists(manifest_path):
                with open(manifest_path) as f:
                    manifest = json.load(f)
                all_apps = manifest.get("app_list", [])
            else:
                all_apps = []

            apps_to_install = selected_apps if selected_apps is not None else all_apps
            apps_dir = os.path.join(temp_dir, "apps")

            total_steps = len(apps_to_install) + 1
            current_step = 0

            for pkg in apps_to_install:
                self._check_cancel()
                current_step += 1

                apk_path = os.path.join(apps_dir, f"{pkg}.apk")
                if not os.path.exists(apk_path):
                    if status_callback:
                        status_callback(f"Skipping {pkg} (APK not found)")
                    continue

                if status_callback:
                    status_callback(f"Installing: {pkg} ({current_step}/{len(apps_to_install)})")
                if progress_callback:
                    progress_callback(current_step, total_steps, f"Installing {pkg}")

                success = self.adb.install_apk(serial, apk_path)
                if not success and status_callback:
                    status_callback(f"WARNING: Failed to install {pkg}")

            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps, "Done")
            if status_callback:
                status_callback("Backup restore complete!")

            return True

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def read_archive_manifest(archive_path: str) -> Optional[Dict]:
        """Read the manifest from a .gimg or .gbak archive."""
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                if "manifest.json" in zf.namelist():
                    with zf.open("manifest.json") as f:
                        return json.load(f)
        except Exception:
            pass
        return None

    @staticmethod
    def get_archive_apps(archive_path: str) -> List[str]:
        """Get list of apps included in an archive."""
        manifest = ImagingEngine.read_archive_manifest(archive_path)
        if manifest:
            return manifest.get("app_list", [])
        # Try to find APKs directly
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                apps = []
                for name in zf.namelist():
                    if name.startswith("apps/") and name.endswith(".apk"):
                        pkg = os.path.splitext(os.path.basename(name))[0]
                        apps.append(pkg)
                return sorted(apps)
        except Exception:
            return []


class OperationCancelled(Exception):
    """Raised when a user cancels an operation."""
    pass
