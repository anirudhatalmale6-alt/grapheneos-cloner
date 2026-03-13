"""
GrapheneOS Cloner - Imaging Engine
Handles creating, storing, and restoring full device images.
Images are stored as compressed archives containing individual partition dumps.
Also supports flashing official GrapheneOS factory images.
"""
import os
import json
import zipfile
import shutil
import tempfile
import time
import subprocess
import glob as globmod
from typing import Optional, List, Dict, Callable
from dataclasses import dataclass, asdict

from config import (
    PIXEL3_PARTITIONS, SYSTEM_PARTITIONS, DATA_PARTITION,
    IMAGE_EXTENSION, ARCHIVE_EXTENSION, BACKUP_EXTENSION,
    get_default_image_dir, get_default_backup_dir,
    get_partitions_for_device, get_device_friendly_name,
    DEVICE_PARTITIONS, DEFAULT_PARTITIONS,
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
                     mode: str = "adb",
                     progress_callback: Optional[Callable] = None,
                     status_callback: Optional[Callable] = None) -> str:
        """
        Create a full device image from a connected device.
        Uses ADB with root (primary) or fastboot (fallback) to dump partitions.

        Args:
            serial: Device serial number
            output_path: Directory to save the image archive
            partitions: List of partitions to capture (default: all)
            mode: "adb" (device in ADB mode, requires root) or "fastboot"
            progress_callback: Called with (current_step, total_steps, message)
            status_callback: Called with status message strings

        Returns:
            Path to the created .gimg archive
        """
        self._cancel_flag = False

        if status_callback:
            status_callback("Preparing to create image...")

        # Create temp directory for partition dumps
        temp_dir = tempfile.mkdtemp(prefix="gcloner_")

        try:
            # Get device info and auto-detect partition layout
            if status_callback:
                status_callback("Getting device information...")

            if mode == "adb":
                device_info = self.adb.get_device_info(serial)
                device_codename = device_info.get("device", "").lower()

                # Enable root access for partition reading
                if status_callback:
                    status_callback("Enabling root access...")
                root_ok = self.adb.enable_root(serial)
                if root_ok:
                    # Verify root is actually working
                    if not self.adb.is_root(serial):
                        root_ok = False

                if not root_ok:
                    error_msg = (
                        "ROOT ACCESS FAILED!\n\n"
                        "Image creation requires root access to read device partitions.\n"
                        "Without root, all partition dumps will be empty (0 bytes).\n\n"
                        "To fix this on GrapheneOS:\n"
                        "1. Go to Settings → System → Developer Options\n"
                        "2. Find 'Root access' or 'Enable root access via ADB'\n"
                        "3. Turn it ON\n"
                        "4. Reconnect USB and try again\n\n"
                        "ALTERNATIVE: If root is not available, use 'Clone from Factory Image'\n"
                        "on the Clone Device page instead. This downloads the official\n"
                        "GrapheneOS image and flashes it to target devices."
                    )
                    if status_callback:
                        status_callback(f"ERROR: {error_msg}")
                    raise Exception(error_msg)
            else:
                # Fastboot mode cannot read partitions on Pixel devices
                error_msg = (
                    "FASTBOOT MODE CANNOT READ PARTITIONS!\n\n"
                    "Fastboot is designed for writing/flashing, not reading.\n"
                    "The 'fastboot fetch' command is not supported on Pixel devices.\n\n"
                    "OPTIONS:\n"
                    "1. Switch to ADB mode: Boot the phone normally with USB debugging ON,\n"
                    "   enable root access in Developer Options, then try again.\n\n"
                    "2. Use 'Clone from Factory Image' on the Clone Device page:\n"
                    "   This downloads the official GrapheneOS image and flashes it\n"
                    "   to target devices — no root or image capture needed!"
                )
                if status_callback:
                    status_callback(f"ERROR: {error_msg}")
                raise Exception(error_msg)

            friendly_name = get_device_friendly_name(device_codename)

            if not partitions:
                partitions = get_partitions_for_device(device_codename)

            if status_callback:
                status_callback(f"Detected device: {friendly_name} ({device_codename})")
                status_callback(f"Will dump {len(partitions)} partitions: {', '.join(partitions)}")

            total_steps = len(partitions) + 2  # partitions + manifest + archive
            current_step = 0

            # Get app list via ADB
            app_list = []
            if mode == "adb":
                try:
                    app_list = self.adb.get_installed_packages(serial)
                    if status_callback:
                        status_callback(f"Found {len(app_list)} installed apps")
                except Exception:
                    pass

            failed_partitions = []

            # Dump each partition
            for partition in partitions:
                self._check_cancel()
                current_step += 1

                if status_callback:
                    status_callback(f"Dumping partition: {partition} ({current_step}/{len(partitions)})")
                if progress_callback:
                    progress_callback(current_step, total_steps, f"Dumping {partition}")

                img_path = os.path.join(temp_dir, f"{partition}{IMAGE_EXTENSION}")

                def _part_progress(line, _p=partition):
                    if status_callback:
                        status_callback(f"  {line}")

                success = False

                if mode == "adb":
                    # Primary method: ADB with dd
                    success = self.adb.dump_partition(serial, partition, img_path, _part_progress)

                if not success and mode == "fastboot":
                    # Fastboot fetch method
                    success = self.fastboot.fetch_partition(serial, partition, img_path, _part_progress)

                if not success:
                    failed_partitions.append(partition)
                    if status_callback:
                        status_callback(f"  WARNING: Could not dump {partition}")
                    # Create empty placeholder
                    with open(img_path, 'wb') as f:
                        pass

            self._check_cancel()

            if len(failed_partitions) == len(partitions):
                error_msg = (
                    f"ALL {len(partitions)} partitions failed to dump!\n"
                    "This usually means root access is not working properly.\n"
                    "The resulting image would be empty and unusable.\n\n"
                    "Make sure root access via ADB is enabled in Developer Options."
                )
                if status_callback:
                    status_callback(f"ERROR: {error_msg}")
                raise Exception(error_msg)

            if failed_partitions and status_callback:
                status_callback(f"Note: {len(failed_partitions)} partition(s) could not be read: {', '.join(failed_partitions)}")

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
                device_serial=device_info.get("serial", device_info.get("serialno", serial)),
                device_model=device_codename or "unknown",
                device_product=friendly_name,
                grapheneos_build=device_info.get("build", device_info.get("variant", "unknown")),
                created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                partitions=[p for p in partitions if p not in failed_partitions],
                app_list=app_list,
                total_size_bytes=total_size,
            )

            manifest_path = os.path.join(temp_dir, "manifest.json")
            with open(manifest_path, "w") as f:
                json.dump(asdict(manifest), f, indent=2)

            # Create compressed archive
            current_step += 1
            if status_callback:
                status_callback("Creating compressed archive (this may take a while for large images)...")
            if progress_callback:
                progress_callback(current_step, total_steps, "Compressing archive")

            os.makedirs(output_path, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            model = device_codename or "pixel"
            archive_name = f"{model}_{timestamp}{ARCHIVE_EXTENSION}"
            archive_path = os.path.join(output_path, archive_name)

            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(manifest_path, "manifest.json")
                for partition in partitions:
                    img_file = f"{partition}{IMAGE_EXTENSION}"
                    img_full = os.path.join(temp_dir, img_file)
                    if os.path.exists(img_full) and os.path.getsize(img_full) > 0:
                        zf.write(img_full, img_file)

            if status_callback:
                status_callback(f"Image created: {archive_name}")

            return archive_path

        finally:
            # Cleanup temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)

    def check_oem_unlocked(self, serial: str) -> tuple:
        """
        Check if a device in fastboot mode has its bootloader unlocked.

        Returns:
            (is_unlocked: bool, message: str)
        """
        unlocked = self.fastboot.get_var(serial, "unlocked")
        if unlocked is None:
            return False, "Could not read bootloader lock status"
        if unlocked.lower() in ("yes", "true"):
            return True, "Bootloader is unlocked"
        return False, "Bootloader is LOCKED - flashing will fail"

    def unlock_bootloader(self, serial: str,
                          status_callback: Optional[Callable] = None) -> tuple:
        """
        Attempt to unlock the bootloader on a fastboot device.
        NOTE: OEM unlocking must first be enabled in Settings > Developer Options.

        Returns:
            (success: bool, message: str)
        """
        if status_callback:
            status_callback("Checking bootloader status...")

        is_unlocked, msg = self.check_oem_unlocked(serial)
        if is_unlocked:
            if status_callback:
                status_callback("Bootloader is already unlocked!")
            return True, "Already unlocked"

        if status_callback:
            status_callback("Attempting to unlock bootloader...")
            status_callback("NOTE: You may need to confirm on the device screen!")

        success, output = self.fastboot.oem_unlock(serial)

        if success:
            if status_callback:
                status_callback("Bootloader unlocked successfully! Device will reboot.")
            return True, "Bootloader unlocked"
        else:
            msg = "Failed to unlock bootloader. "
            if "FAIL" in output.upper():
                msg += "Make sure OEM unlocking is enabled in Settings > Developer Options."
            if status_callback:
                status_callback(msg)
            return False, msg

    def lock_bootloader(self, serial: str,
                        status_callback: Optional[Callable] = None) -> tuple:
        """
        Lock the bootloader on a fastboot device.
        NOTE: This will erase all data on the device!

        Returns:
            (success: bool, message: str)
        """
        if status_callback:
            status_callback("Checking bootloader status...")

        is_unlocked, msg = self.check_oem_unlocked(serial)
        if not is_unlocked:
            if status_callback:
                status_callback("Bootloader is already locked!")
            return True, "Already locked"

        if status_callback:
            status_callback("Locking bootloader...")
            status_callback("NOTE: You may need to confirm on the device screen!")

        success, output = self.fastboot.oem_lock(serial)

        if success:
            if status_callback:
                status_callback("Bootloader locked successfully! Device will reboot.")
            return True, "Bootloader locked"
        else:
            msg = "Failed to lock bootloader. "
            if status_callback:
                status_callback(msg + output)
            return False, msg + output

    def restore_image(self, serial: str, archive_path: str,
                      partitions: Optional[List[str]] = None,
                      progress_callback: Optional[Callable] = None,
                      status_callback: Optional[Callable] = None) -> dict:
        """
        Restore a device image to a connected device in fastboot mode.

        Args:
            serial: Device serial number
            archive_path: Path to the .gimg or .gbak archive
            partitions: Specific partitions to restore (default: all in archive)
            progress_callback: Called with (current_step, total_steps, message)
            status_callback: Called with status message strings

        Returns:
            dict with keys: success (bool), flashed (list), failed (list), message (str)
        """
        self._cancel_flag = False
        result = {"success": False, "flashed": [], "failed": [], "message": ""}

        if status_callback:
            status_callback("Preparing to restore image...")

        # ── Step 1: Check bootloader unlock status ──
        if status_callback:
            status_callback("Checking bootloader status...")

        is_unlocked, unlock_msg = self.check_oem_unlocked(serial)
        if not is_unlocked:
            result["message"] = (
                "BOOTLOADER IS LOCKED! Flashing cannot proceed.\n"
                "To unlock:\n"
                "1. On the phone: Settings → System → Developer Options → Enable 'OEM unlocking'\n"
                "2. In this app: Click 'Unlock Bootloader' button before cloning\n"
                "Or run from command line: fastboot flashing unlock"
            )
            if status_callback:
                status_callback(f"ERROR: {result['message']}")
            return result

        if status_callback:
            status_callback("Bootloader is unlocked - proceeding with flash...")

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

                def _flash_progress(line, _p=partition):
                    if status_callback:
                        status_callback(f"  {_p}: {line}")

                success = self.fastboot.flash_partition(serial, partition, img_path, _flash_progress)
                if success:
                    result["flashed"].append(partition)
                    if status_callback:
                        status_callback(f"  ✓ {partition} flashed successfully")
                else:
                    result["failed"].append(partition)
                    if status_callback:
                        status_callback(f"  ✗ FAILED to flash {partition}")

            # Check results
            if not result["flashed"]:
                result["message"] = (
                    f"ALL {len(result['failed'])} partitions failed to flash! "
                    "The device bootloader may still be locked, or the image is incompatible."
                )
                if status_callback:
                    status_callback(f"ERROR: {result['message']}")
                return result

            # Set active slot
            if status_callback:
                status_callback("Setting active slot...")
            self.fastboot.set_active_slot(serial, "a")

            # Reboot
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps, "Rebooting device")
            if status_callback:
                status_callback("Rebooting device...")

            self.fastboot.reboot(serial)

            # Build final message
            if result["failed"]:
                result["success"] = True  # Partial success
                result["message"] = (
                    f"Partial clone: {len(result['flashed'])} partitions flashed, "
                    f"{len(result['failed'])} failed ({', '.join(result['failed'])})"
                )
            else:
                result["success"] = True
                result["message"] = f"All {len(result['flashed'])} partitions flashed successfully!"

            if status_callback:
                status_callback(result["message"])

            return result

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def flash_factory_image(self, serial: str, factory_zip_path: str,
                            progress_callback: Optional[Callable] = None,
                            status_callback: Optional[Callable] = None) -> dict:
        """
        Flash an official GrapheneOS factory image ZIP to a device in fastboot mode.
        This is the recommended way to clone GrapheneOS — no root needed.

        The factory image ZIP should contain .img files (boot.img, system.img, etc.)
        and optionally a flash-all script.

        Args:
            serial: Device serial number (must be in fastboot mode)
            factory_zip_path: Path to the factory image ZIP file
            progress_callback: Called with (current_step, total_steps, message)
            status_callback: Called with status message strings

        Returns:
            dict with keys: success (bool), flashed (list), failed (list), message (str)
        """
        self._cancel_flag = False
        result = {"success": False, "flashed": [], "failed": [], "message": ""}

        if status_callback:
            status_callback("Preparing to flash factory image...")

        # Check bootloader
        is_unlocked, unlock_msg = self.check_oem_unlocked(serial)
        if not is_unlocked:
            result["message"] = (
                "BOOTLOADER IS LOCKED! Flashing cannot proceed.\n"
                "Click 'Unlock Bootloader' first."
            )
            if status_callback:
                status_callback(f"ERROR: {result['message']}")
            return result

        temp_dir = tempfile.mkdtemp(prefix="gcloner_factory_")

        try:
            # Extract the factory ZIP
            if status_callback:
                status_callback("Extracting factory image...")

            with zipfile.ZipFile(factory_zip_path, "r") as zf:
                zf.extractall(temp_dir)

            # Find all .img files (they may be in a subdirectory)
            img_files = []
            for root, dirs, files in os.walk(temp_dir):
                for f in files:
                    if f.endswith(".img"):
                        img_files.append(os.path.join(root, f))

            if not img_files:
                result["message"] = "No .img files found in the ZIP. Make sure this is a valid GrapheneOS factory image."
                if status_callback:
                    status_callback(f"ERROR: {result['message']}")
                return result

            # Check for nested ZIP (GrapheneOS factory images contain an inner image ZIP)
            inner_zips = []
            for root, dirs, files in os.walk(temp_dir):
                for f in files:
                    if f.endswith(".zip") and "image" in f.lower():
                        inner_zips.append(os.path.join(root, f))

            if inner_zips:
                if status_callback:
                    status_callback("Found inner image archive, extracting...")
                for iz in inner_zips:
                    with zipfile.ZipFile(iz, "r") as zf:
                        zf.extractall(temp_dir)
                # Re-scan for img files
                img_files = []
                for root, dirs, files in os.walk(temp_dir):
                    for f in files:
                        if f.endswith(".img"):
                            img_files.append(os.path.join(root, f))

            # Map partition names from filenames
            partition_map = {}
            for img_path in img_files:
                fname = os.path.basename(img_path)
                part_name = fname.replace(".img", "")
                # Skip android-info.txt artifacts
                if part_name in ("android-info",):
                    continue
                partition_map[part_name] = img_path

            if status_callback:
                parts_list = ", ".join(sorted(partition_map.keys()))
                status_callback(f"Found {len(partition_map)} partitions to flash: {parts_list}")

            total_steps = len(partition_map) + 2  # partitions + slot + reboot
            current_step = 0

            # Flash each partition
            for part_name, img_path in sorted(partition_map.items()):
                self._check_cancel()
                current_step += 1

                if status_callback:
                    size_mb = os.path.getsize(img_path) / 1048576
                    status_callback(f"Flashing {part_name} ({size_mb:.1f} MB)... ({current_step}/{len(partition_map)})")
                if progress_callback:
                    progress_callback(current_step, total_steps, f"Flashing {part_name}")

                def _flash_progress(line, _p=part_name):
                    if status_callback:
                        status_callback(f"  {_p}: {line}")

                success = self.fastboot.flash_partition(serial, part_name, img_path, _flash_progress)
                if success:
                    result["flashed"].append(part_name)
                    if status_callback:
                        status_callback(f"  ✓ {part_name} flashed successfully")
                else:
                    result["failed"].append(part_name)
                    if status_callback:
                        status_callback(f"  ✗ FAILED to flash {part_name}")

            if not result["flashed"]:
                result["message"] = f"ALL partitions failed to flash!"
                if status_callback:
                    status_callback(f"ERROR: {result['message']}")
                return result

            # Set active slot
            current_step += 1
            if status_callback:
                status_callback("Setting active slot...")
            if progress_callback:
                progress_callback(current_step, total_steps, "Setting slot")
            self.fastboot.set_active_slot(serial, "a")

            # Reboot
            current_step += 1
            if status_callback:
                status_callback("Rebooting device...")
            if progress_callback:
                progress_callback(current_step, total_steps, "Rebooting")
            self.fastboot.reboot(serial)

            if result["failed"]:
                result["success"] = True
                result["message"] = (
                    f"Partial: {len(result['flashed'])} flashed, "
                    f"{len(result['failed'])} failed ({', '.join(result['failed'])})"
                )
            else:
                result["success"] = True
                result["message"] = f"All {len(result['flashed'])} partitions flashed! Device is rebooting."

            if status_callback:
                status_callback(result["message"])

            return result

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
