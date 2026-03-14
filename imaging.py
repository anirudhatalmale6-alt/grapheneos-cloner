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

    def _flash_partitions_individually(self, serial: str, img_dir: str,
                                        status_callback: Optional[Callable] = None) -> dict:
        """
        Flash individual .img files from an extracted image directory.
        Handles A/B slot devices by flashing each partition to both slots.
        Returns dict with 'flashed' and 'failed' lists.
        """
        result = {"flashed": [], "failed": []}

        # Partitions that are NOT slot-specific (no _a/_b suffix)
        non_slotted = {"userdata", "metadata", "persist", "misc"}

        # Collect all .img files
        img_files = []
        for f in sorted(os.listdir(img_dir)):
            if not f.endswith(".img"):
                continue
            part_name = f[:-4]  # strip .img
            if part_name in ("android-info",):
                continue
            img_files.append((part_name, os.path.join(img_dir, f)))

        if not img_files:
            return result

        for part_name, img_path in img_files:
            if os.path.getsize(img_path) == 0:
                if status_callback:
                    status_callback(f"  Skipping {part_name} (empty)")
                continue

            size_mb = os.path.getsize(img_path) / 1048576

            if part_name in non_slotted:
                # Flash without slot suffix
                if status_callback:
                    status_callback(f"  Flashing {part_name} ({size_mb:.1f} MB)...")
                ok = self.fastboot.flash_partition(serial, part_name, img_path)
                if ok:
                    result["flashed"].append(part_name)
                    if status_callback:
                        status_callback(f"    ✓ {part_name}")
                else:
                    result["failed"].append(part_name)
                    if status_callback:
                        status_callback(f"    ✗ {part_name} FAILED")
            else:
                # A/B device: flash to both slots
                for slot in ["a", "b"]:
                    slot_name = f"{part_name}_{slot}"
                    if status_callback:
                        status_callback(f"  Flashing {slot_name} ({size_mb:.1f} MB)...")
                    ok = self.fastboot.flash_partition(serial, slot_name, img_path)
                    if ok:
                        result["flashed"].append(slot_name)
                        if status_callback:
                            status_callback(f"    ✓ {slot_name}")
                    else:
                        result["failed"].append(slot_name)
                        if status_callback:
                            status_callback(f"    ✗ {slot_name} FAILED")

        return result

    def flash_factory_image(self, serial: str, factory_zip_path: str,
                            progress_callback: Optional[Callable] = None,
                            status_callback: Optional[Callable] = None) -> dict:
        """
        Flash an official GrapheneOS factory image ZIP to a device in fastboot mode.

        Priority order:
        1. Run official flash-all script (most reliable, supports locked bootloader)
        2. fastboot flashall with ANDROID_PRODUCT_OUT (same as script internally)
        3. fastboot update (handles A/B slots from ZIP)
        4. Individual partition flashing (last resort, no locked bootloader support)

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

        # Use SHORT temp path to avoid Windows 260-char path limit
        temp_dir = os.path.join(tempfile.gettempdir(), "gc_flash")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        os.makedirs(temp_dir, exist_ok=True)

        try:
            # Extract the factory ZIP
            if status_callback:
                status_callback("Extracting factory image...")

            with zipfile.ZipFile(factory_zip_path, "r") as zf:
                zf.extractall(temp_dir)

            # Find key files in the extracted factory image
            bootloader_img = None
            radio_img = None
            inner_image_zip = None
            avb_key = None
            flash_script = None
            script_dir = None

            for root, dirs, files in os.walk(temp_dir):
                for f in files:
                    full_path = os.path.join(root, f)
                    if f.startswith("bootloader-") and f.endswith(".img"):
                        bootloader_img = full_path
                    elif f.startswith("radio-") and f.endswith(".img"):
                        radio_img = full_path
                    elif f.endswith(".zip") and "image" in f.lower():
                        inner_image_zip = full_path
                    elif f == "avb_pkmd.bin":
                        avb_key = full_path
                    elif f == "flash-all.bat" and os.name == "nt":
                        flash_script = full_path
                        script_dir = root
                    elif f == "flash-all.sh" and os.name != "nt":
                        flash_script = full_path
                        script_dir = root

            if not inner_image_zip and not flash_script:
                img_files = []
                for root, dirs, files in os.walk(temp_dir):
                    for f in files:
                        if f.endswith(".img") and not f.startswith("bootloader-") and not f.startswith("radio-"):
                            img_files.append(f)
                if not img_files:
                    result["message"] = "No image files found in ZIP. Make sure this is a valid GrapheneOS factory image."
                    if status_callback:
                        status_callback(f"ERROR: {result['message']}")
                    return result

            if status_callback:
                found = []
                if flash_script:
                    found.append(f"flash script ({os.path.basename(flash_script)})")
                if bootloader_img:
                    found.append(f"bootloader ({os.path.basename(bootloader_img)})")
                if radio_img:
                    found.append(f"radio ({os.path.basename(radio_img)})")
                if inner_image_zip:
                    found.append(f"image archive ({os.path.basename(inner_image_zip)})")
                if avb_key:
                    found.append("AVB key (avb_pkmd.bin)")
                status_callback(f"Found: {', '.join(found)}")

            total_steps = 5
            system_flashed = False
            used_method = ""

            # =====================================================
            # METHOD 1: Run the official flash-all script
            # This is the MOST RELIABLE method — it's what GrapheneOS
            # officially recommends and handles everything correctly
            # including verified boot chain for locked bootloader.
            # =====================================================
            if flash_script and script_dir:
                self._check_cancel()
                if status_callback:
                    status_callback("")
                    status_callback("=== Method 1: Running official flash-all script ===")
                    status_callback("This is the GrapheneOS-recommended flashing method.")
                    status_callback("It handles bootloader, radio, system images, and slot management.")
                    status_callback("")
                if progress_callback:
                    progress_callback(1, total_steps, "Running flash-all script")

                def _script_progress(line):
                    if status_callback:
                        status_callback(f"  {line}")

                script_ok, script_output = self.fastboot.run_flash_script(
                    flash_script, script_dir,
                    progress_callback=_script_progress
                )

                if script_ok:
                    result["flashed"].append("all (via flash-all script)")
                    system_flashed = True
                    used_method = "flash-all script"
                    if status_callback:
                        status_callback("  ✓ Flash-all script completed successfully!")
                else:
                    if status_callback:
                        status_callback(f"  ✗ Flash-all script failed: {script_output}")
                        status_callback("")

            # =====================================================
            # METHOD 2: fastboot flashall with ANDROID_PRODUCT_OUT
            # Same as what flash-all script does internally, but we
            # handle bootloader/radio ourselves first.
            # =====================================================
            if not system_flashed and inner_image_zip:
                self._check_cancel()
                if status_callback:
                    status_callback("=== Method 2: fastboot flashall ===")

                # Flash bootloader first
                if bootloader_img:
                    if status_callback:
                        status_callback("Flashing bootloader...")
                    ok = self.fastboot.flash_partition(serial, "bootloader", bootloader_img)
                    if ok:
                        result["flashed"].append("bootloader")
                        if status_callback:
                            status_callback("  ✓ bootloader")
                        self.fastboot.reboot_to_bootloader(serial)
                        if not self.fastboot.wait_for_device(serial, timeout=30):
                            time.sleep(10)
                    else:
                        if status_callback:
                            status_callback("  ✗ bootloader flash failed")

                # Flash radio
                if radio_img:
                    if status_callback:
                        status_callback("Flashing radio...")
                    ok = self.fastboot.flash_partition(serial, "radio", radio_img)
                    if ok:
                        result["flashed"].append("radio")
                        if status_callback:
                            status_callback("  ✓ radio")
                        self.fastboot.reboot_to_bootloader(serial)
                        if not self.fastboot.wait_for_device(serial, timeout=30):
                            time.sleep(10)
                    else:
                        if status_callback:
                            status_callback("  ✗ radio flash failed")

                # Extract inner ZIP and use flashall
                if status_callback:
                    status_callback("Extracting system images...")

                inner_dir = os.path.join(temp_dir, "_imgs")
                os.makedirs(inner_dir, exist_ok=True)
                with zipfile.ZipFile(inner_image_zip, "r") as zf:
                    zf.extractall(inner_dir)

                if status_callback:
                    img_count = sum(1 for f in os.listdir(inner_dir) if f.endswith(".img"))
                    status_callback(f"Running 'fastboot flashall' with {img_count} images...")

                if progress_callback:
                    progress_callback(2, total_steps, "fastboot flashall")

                def _flashall_progress(line):
                    if status_callback:
                        status_callback(f"  {line}")

                fa_ok, fa_output = self.fastboot.flashall(
                    serial, inner_dir, wipe=True,
                    progress_callback=_flashall_progress
                )

                if fa_ok:
                    result["flashed"].append("system (flashall)")
                    system_flashed = True
                    used_method = "fastboot flashall"
                    if status_callback:
                        status_callback("  ✓ flashall completed successfully!")
                else:
                    if status_callback:
                        status_callback(f"  ✗ flashall failed: {fa_output}")
                        status_callback("")

            # =====================================================
            # METHOD 3: fastboot update (ZIP-based)
            # =====================================================
            if not system_flashed and inner_image_zip:
                self._check_cancel()
                if status_callback:
                    status_callback("=== Method 3: fastboot update ===")

                short_zip = os.path.join(temp_dir, "image.zip")
                if inner_image_zip != short_zip:
                    shutil.copy2(inner_image_zip, short_zip)

                def _update_progress(line):
                    if status_callback:
                        status_callback(f"  {line}")

                if progress_callback:
                    progress_callback(3, total_steps, "fastboot update")

                update_ok, update_output = self.fastboot.update(
                    serial, short_zip, wipe=True,
                    progress_callback=_update_progress
                )

                if update_ok:
                    result["flashed"].append("system (fastboot update)")
                    system_flashed = True
                    used_method = "fastboot update"
                    if status_callback:
                        status_callback("  ✓ fastboot update succeeded!")
                else:
                    if status_callback:
                        status_callback(f"  ✗ fastboot update failed: {update_output}")
                        status_callback("")

            # =====================================================
            # METHOD 4: Individual partition flashing (last resort)
            # WARNING: Does NOT support locked bootloader!
            # =====================================================
            if not system_flashed:
                self._check_cancel()
                if status_callback:
                    status_callback("=== Method 4: Individual partition flash (last resort) ===")
                    status_callback("WARNING: This method does NOT support bootloader locking!")

                if progress_callback:
                    progress_callback(3, total_steps, "Individual partition flash")

                # Make sure bootloader/radio are flashed if not already
                if bootloader_img and "bootloader" not in result["flashed"]:
                    ok = self.fastboot.flash_partition(serial, "bootloader", bootloader_img)
                    if ok:
                        result["flashed"].append("bootloader")
                        self.fastboot.reboot_to_bootloader(serial)
                        self.fastboot.wait_for_device(serial, timeout=30)

                if radio_img and "radio" not in result["flashed"]:
                    ok = self.fastboot.flash_partition(serial, "radio", radio_img)
                    if ok:
                        result["flashed"].append("radio")
                        self.fastboot.reboot_to_bootloader(serial)
                        self.fastboot.wait_for_device(serial, timeout=30)

                # Extract inner ZIP if not already
                inner_dir = os.path.join(temp_dir, "_imgs")
                if not os.path.exists(inner_dir) and inner_image_zip:
                    os.makedirs(inner_dir, exist_ok=True)
                    with zipfile.ZipFile(inner_image_zip, "r") as zf:
                        zf.extractall(inner_dir)

                flash_dir = inner_dir if os.path.exists(inner_dir) else temp_dir
                ind_result = self._flash_partitions_individually(
                    serial, flash_dir, status_callback=status_callback
                )
                result["flashed"].extend(ind_result["flashed"])
                result["failed"].extend(ind_result["failed"])

                if ind_result["flashed"]:
                    system_flashed = True
                    used_method = "individual partition flash"
                    self.fastboot.set_active_slot(serial, "a")
                    self.fastboot.erase_partition(serial, "userdata")

            # Flash AVB custom key if available and system was flashed
            # (only meaningful for methods 2-4; method 1 handles it via script)
            if system_flashed and avb_key and used_method != "flash-all script":
                if status_callback:
                    status_callback("Flashing AVB custom key (for bootloader locking)...")
                ok = self.fastboot.flash_partition(serial, "avb_custom_key", avb_key)
                if ok:
                    result["flashed"].append("avb_custom_key")
                    if status_callback:
                        status_callback("  ✓ AVB key flashed")
                else:
                    if status_callback:
                        status_callback("  ✗ AVB key flash failed")

            # Reboot (skip if flash-all script already rebooted)
            if system_flashed and used_method != "flash-all script":
                if progress_callback:
                    progress_callback(4, total_steps, "Rebooting")
                if status_callback:
                    status_callback("Rebooting device...")
                self.fastboot.reboot(serial)

            # Final result
            if progress_callback:
                progress_callback(5, total_steps, "Complete")

            if not system_flashed:
                result["message"] = (
                    "FLASH FAILED — all 4 methods failed.\n"
                    "Check:\n"
                    "1. Device is in fastboot mode (Power + Volume Down)\n"
                    "2. USB cable is connected firmly\n"
                    "3. Bootloader is unlocked\n"
                    "4. Correct factory image for your device\n"
                    "\nSee log above for details."
                )
            elif used_method == "individual partition flash":
                result["success"] = True
                result["message"] = (
                    f"GrapheneOS flashed via {used_method}.\n"
                    "WARNING: Bootloader locking is NOT supported with this method.\n"
                    "The device will work with unlocked bootloader."
                )
            else:
                result["success"] = True
                result["message"] = (
                    f"GrapheneOS flashed successfully via {used_method}!\n"
                    "Device should boot into GrapheneOS setup screen.\n"
                    "You can safely lock the bootloader after setup."
                )

            if status_callback:
                status_callback(result["message"])

            return result

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def create_backup(self, serial: str, output_path: str,
                      include_apps: bool = True,
                      user_ids: Optional[List[int]] = None,
                      progress_callback: Optional[Callable] = None,
                      status_callback: Optional[Callable] = None) -> str:
        """
        Create a backup of a device (ADB mode).
        Captures app APKs from one or more user profiles.

        Args:
            serial: Device serial number
            output_path: Directory to save backup
            include_apps: Whether to include app APKs
            user_ids: List of user profile IDs to backup (None = all profiles)
            progress_callback: Progress updates
            status_callback: Status messages

        Returns:
            Path to the created .gbak backup file
        """
        self._cancel_flag = False
        os.makedirs(output_path, exist_ok=True)

        temp_dir = tempfile.mkdtemp(prefix="gcloner_backup_")

        # Diagnostic log file for backup
        log_path = os.path.join(output_path, f"backup_diagnostic_{time.strftime('%Y%m%d_%H%M%S')}.log")
        diag_log = open(log_path, "w", encoding="utf-8")

        def _log(msg):
            ts = time.strftime("%H:%M:%S")
            diag_log.write(f"[{ts}] {msg}\n")
            diag_log.flush()
            if status_callback:
                status_callback(msg)

        try:
            _log("Getting device info...")

            device_info = self.adb.get_device_info(serial)
            _log(f"Device: {device_info}")

            # Discover all user profiles on the device
            all_users = self.adb.list_users(serial)
            user_names = ", ".join(f"User {u['id']} ({u['name']})" for u in all_users)
            _log(f"Found {len(all_users)} user profile(s): {user_names}")

            # Filter to requested user IDs (default = all)
            if user_ids is not None:
                target_users = [u for u in all_users if int(u['id']) in user_ids]
            else:
                target_users = all_users

            if not target_users:
                target_users = [{"id": "0", "name": "Owner"}]

            # Collect apps per user profile
            user_app_map = {}  # user_id -> [packages]
            all_apks_needed = set()

            if include_apps:
                for user in target_users:
                    uid = int(user['id'])
                    _log(f"Scanning apps for User {uid} ({user['name']})...")
                    _log(f"  Running: pm list packages --user {uid} -3")
                    pkgs = self.adb.get_user_packages(serial, user_id=uid)
                    user_app_map[str(uid)] = pkgs
                    all_apks_needed.update(pkgs)
                    _log(f"  Found {len(pkgs)} apps for User {uid}: {sorted(pkgs)}")

            # ── Capture per-user system settings ──
            # Settings that can be read/written via ADB without root
            SKIP_SETTINGS = {
                "android_id", "bluetooth_address", "advertising_id",
                "install_non_market_apps",
            }

            user_settings_map = {}  # user_id -> {namespace -> {key: value}}
            global_settings = {}

            for user in target_users:
                uid = int(user['id'])
                if status_callback:
                    status_callback(f"Capturing settings for User {uid} ({user['name']})...")

                user_s = {}
                for ns in ("system", "secure"):
                    raw = self.adb.get_settings(serial, ns, user_id=uid)
                    filtered = {k: v for k, v in raw.items()
                                if k not in SKIP_SETTINGS and v != "null"}
                    user_s[ns] = filtered
                    if status_callback:
                        status_callback(f"  {ns}: {len(filtered)} settings captured")

                user_settings_map[str(uid)] = user_s

            # Global settings (shared across users, capture once)
            if status_callback:
                status_callback("Capturing global settings...")
            raw_global = self.adb.get_settings(serial, "global")
            global_settings = {k: v for k, v in raw_global.items()
                               if k not in SKIP_SETTINGS and v != "null"}
            if status_callback:
                status_callback(f"  global: {len(global_settings)} settings captured")

            # ── Capture per-app permissions ──
            user_permissions_map = {}  # user_id -> {package -> [permissions]}
            if include_apps:
                for user in target_users:
                    uid = int(user['id'])
                    uid_str = str(uid)
                    user_perms = {}
                    pkgs = user_app_map.get(uid_str, [])
                    if pkgs and status_callback:
                        status_callback(f"Capturing app permissions for User {uid}...")
                    for pkg in pkgs:
                        perms = self.adb.get_granted_permissions(serial, pkg, uid)
                        if perms:
                            user_perms[pkg] = perms
                    user_permissions_map[uid_str] = user_perms
                    if status_callback and pkgs:
                        apps_with_perms = sum(1 for p in user_perms.values() if p)
                        status_callback(f"  {apps_with_perms} apps have granted permissions")

            total_apps = len(all_apks_needed)
            total_steps = total_apps + 3 if include_apps else 3
            current_step = 0

            # Backup APKs — use per-user pm path to find APK for each package
            apps_dir = os.path.join(temp_dir, "apps")
            os.makedirs(apps_dir, exist_ok=True)

            # Build map: package -> list of user_ids where it's installed
            pkg_to_users = {}
            for uid_str, pkgs in user_app_map.items():
                for pkg in pkgs:
                    pkg_to_users.setdefault(pkg, []).append(int(uid_str))

            if include_apps and all_apks_needed:
                pulled_ok = 0
                pulled_fail = 0
                for pkg in sorted(all_apks_needed):
                    self._check_cancel()
                    current_step += 1

                    if status_callback:
                        status_callback(f"Backing up app: {pkg} ({current_step}/{total_apps})")
                    if progress_callback:
                        progress_callback(current_step, total_steps, f"Backup {pkg}")

                    local_apk = os.path.join(apps_dir, f"{pkg}.apk")
                    owner_uids = pkg_to_users.get(pkg, [0])
                    ok = False

                    # Try each user_id where this app is installed
                    for try_uid in owner_uids:
                        _log(f"  [{pkg}] Trying pm path --user {try_uid} ...")
                        rc, out, err = self.adb.shell(serial,
                            f"pm path --user {try_uid} {pkg}")
                        raw = (out or "").strip()
                        _log(f"    pm path rc={rc}, output='{raw}'")

                        if rc != 0 or not raw:
                            continue

                        # Parse all APK paths (split APKs have multiple lines)
                        apk_paths = []
                        for line in raw.split("\n"):
                            line = line.strip()
                            if line.startswith("package:"):
                                apk_paths.append(line.replace("package:", "").strip())
                        _log(f"    Found {len(apk_paths)} APK path(s): {apk_paths}")

                        if not apk_paths:
                            continue

                        # Pull the base/first APK
                        device_path = apk_paths[0]
                        _log(f"    Pulling: {device_path}")
                        pull_ok = self.adb.pull_file(serial, device_path, local_apk)
                        if pull_ok and os.path.exists(local_apk):
                            fsize = os.path.getsize(local_apk)
                            _log(f"    Pull OK! File size: {fsize} bytes")
                            ok = True
                            break
                        else:
                            _log(f"    Pull FAILED for {device_path}")

                    # Fallback: try without --user flag
                    if not ok:
                        _log(f"  [{pkg}] Fallback: pm path without --user ...")
                        rc, out = self.adb.shell(serial, f"pm path {pkg}")
                        raw = (out or "").strip()
                        _log(f"    pm path rc={rc}, output='{raw}'")
                        if rc == 0 and raw:
                            device_path = raw.replace("package:", "").split("\n")[0].strip()
                            if device_path:
                                pull_ok = self.adb.pull_file(serial, device_path, local_apk)
                                if pull_ok and os.path.exists(local_apk):
                                    fsize = os.path.getsize(local_apk)
                                    _log(f"    Fallback pull OK! Size: {fsize} bytes")
                                    ok = True
                                else:
                                    _log(f"    Fallback pull FAILED")

                    if ok:
                        pulled_ok += 1
                    else:
                        pulled_fail += 1
                        _log(f"  [{pkg}] ALL PULL ATTEMPTS FAILED")

                _log(f"\nAPK pull summary: {pulled_ok} OK, {pulled_fail} failed out of {total_apps}")

            # Create manifest with per-user app lists, settings, and permissions
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps, "Creating manifest")

            # Flat app_list for backward compatibility
            flat_app_list = sorted(all_apks_needed) if include_apps else []

            manifest = {
                "type": "backup",
                "device_serial": device_info.get("serial", serial),
                "device_model": device_info.get("model", "unknown"),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "app_list": flat_app_list,
                "user_profiles": [{"id": u["id"], "name": u["name"]} for u in target_users],
                "user_app_map": user_app_map,
                "user_settings": user_settings_map,
                "global_settings": global_settings,
                "user_permissions": user_permissions_map,
                "version": "3.0",
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
            n_users = len(target_users)
            backup_name = f"backup_{model}_{n_users}users_{timestamp}{BACKUP_EXTENSION}"
            backup_path = os.path.join(output_path, backup_name)

            with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        full = os.path.join(root, file)
                        arcname = os.path.relpath(full, temp_dir)
                        zf.write(full, arcname)

            total_settings = sum(
                sum(len(v) for v in ns.values())
                for ns in user_settings_map.values()
            ) + len(global_settings)

            _log(
                f"Backup created: {backup_name}\n"
                f"Profiles: {n_users} | Apps: {total_apps} | Settings: {total_settings}\n"
                f"Includes: APKs, system/secure/global settings, app permissions per profile.\n"
                f"Diagnostic log: {log_path}"
            )

            return backup_path

        finally:
            diag_log.close()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def restore_backup(self, serial: str, backup_path: str,
                       selected_apps: Optional[List[str]] = None,
                       target_user_ids: Optional[List[int]] = None,
                       progress_callback: Optional[Callable] = None,
                       status_callback: Optional[Callable] = None) -> bool:
        """
        Restore a backup to a device (ADB mode).
        Installs selected app APKs to one or more user profiles.

        Args:
            serial: Device serial
            backup_path: Path to .gbak file
            selected_apps: List of package names to install (None = all)
            target_user_ids: User profile IDs to install apps to (None = all from backup)

        Returns:
            True if successful
        """
        self._cancel_flag = False
        temp_dir = tempfile.mkdtemp(prefix="gcloner_brestore_")

        # Open a diagnostic log file alongside the backup
        log_dir = os.path.dirname(backup_path) or "."
        log_path = os.path.join(log_dir, f"restore_diagnostic_{time.strftime('%Y%m%d_%H%M%S')}.log")
        diag_log = open(log_path, "w", encoding="utf-8")

        def _log(msg):
            """Write to both GUI status callback and diagnostic file."""
            ts = time.strftime("%H:%M:%S")
            diag_log.write(f"[{ts}] {msg}\n")
            diag_log.flush()
            if status_callback:
                status_callback(msg)

        try:
            _log("Extracting backup...")

            with zipfile.ZipFile(backup_path, "r") as zf:
                zf.extractall(temp_dir)

            # Read manifest
            manifest_path = os.path.join(temp_dir, "manifest.json")
            manifest = {}
            if os.path.exists(manifest_path):
                with open(manifest_path) as f:
                    manifest = json.load(f)

            all_apps = manifest.get("app_list", [])
            user_app_map = manifest.get("user_app_map", {})
            user_profiles = manifest.get("user_profiles", [])

            apps_to_install = selected_apps if selected_apps is not None else all_apps
            apps_dir = os.path.join(temp_dir, "apps")

            _log(f"Backup manifest: {len(all_apps)} total apps, {len(user_app_map)} user profiles")
            _log(f"User profiles in backup: {user_profiles}")
            for uid_str, apps in user_app_map.items():
                _log(f"  Backup User {uid_str}: {len(apps)} apps → {sorted(apps)}")

            # Determine target users on the device
            device_users = self.adb.list_users(serial)
            user_names = ", ".join(f"User {u['id']} ({u['name']})" for u in device_users)
            _log(f"Target device has {len(device_users)} user profile(s): {user_names}")

            # If backup has multiple user profiles, create missing ones on target
            if user_app_map and len(user_app_map) > 1 and user_profiles:
                existing_ids = {u['id'] for u in device_users}
                uid_remap = {}

                for profile in user_profiles:
                    pid = profile['id']
                    pname = profile.get('name', f'User {pid}')

                    if pid in existing_ids:
                        uid_remap[pid] = pid
                        _log(f"User {pid} ({pname}) already exists on target")
                        continue

                    if pid == '0':
                        uid_remap['0'] = '0'
                        continue

                    _log(f"Creating user profile '{pname}' on target device...")
                    new_uid = self.adb.create_user(serial, pname)
                    if new_uid is not None:
                        uid_remap[pid] = str(new_uid)
                        self.adb.start_user(serial, new_uid)
                        _log(f"  Created user '{pname}' (backup ID {pid} → target ID {new_uid})")
                        time.sleep(3)
                    else:
                        _log(f"  WARNING: Could not create user '{pname}'")

                device_users = self.adb.list_users(serial)
                user_names = ", ".join(f"User {u['id']} ({u['name']})" for u in device_users)
                _log(f"Target device now has {len(device_users)} profile(s): {user_names}")
                _log(f"UID remap: {uid_remap}")

                # Remap user_app_map, settings, permissions
                remapped_app_map = {}
                for old_uid, apps in user_app_map.items():
                    new_uid = uid_remap.get(old_uid)
                    if new_uid is not None:
                        remapped_app_map[new_uid] = apps
                        _log(f"  Remapped apps: User {old_uid} → User {new_uid} ({len(apps)} apps)")
                    else:
                        _log(f"  Skipping apps for backup User {old_uid} (no remap)")
                user_app_map = remapped_app_map

                user_settings_raw = manifest.get("user_settings", {})
                user_perms_raw = manifest.get("user_permissions", {})
                remapped_settings = {}
                remapped_perms = {}
                for old_uid in uid_remap:
                    new_uid = uid_remap[old_uid]
                    if old_uid in user_settings_raw:
                        remapped_settings[new_uid] = user_settings_raw[old_uid]
                    if old_uid in user_perms_raw:
                        remapped_perms[new_uid] = user_perms_raw[old_uid]
                manifest['user_settings'] = remapped_settings
                manifest['user_permissions'] = remapped_perms

            if user_app_map and len(user_app_map) > 1:
                # ══════════════════════════════════════════════
                # MULTI-USER RESTORE — Per-user push + pm install
                # Uses device-side pm install --user which properly
                # respects the --user flag unlike host-side adb install
                # ══════════════════════════════════════════════
                _log("")
                _log("=" * 50)
                _log("MULTI-USER RESTORE — Per-user install via pm")
                _log("=" * 50)

                # Build per-user app sets
                user_app_sets = {}
                all_unique_apps = set()
                for user in device_users:
                    uid_str = user['id']
                    user_apps = user_app_map.get(uid_str, [])
                    if selected_apps:
                        user_apps = [a for a in user_apps if a in selected_apps]
                    user_app_sets[uid_str] = set(user_apps)
                    all_unique_apps.update(user_apps)

                # Show diagnostic info
                _log(f"\nTarget app configuration:")
                for uid_str, apps in sorted(user_app_sets.items()):
                    _log(f"  User {uid_str}: {len(apps)} apps → {sorted(apps)}")

                uid_list = sorted(user_app_sets.keys())
                if len(uid_list) == 2:
                    u1, u2 = uid_list
                    only_u1 = user_app_sets[u1] - user_app_sets[u2]
                    only_u2 = user_app_sets[u2] - user_app_sets[u1]
                    shared = user_app_sets[u1] & user_app_sets[u2]
                    _log(f"\n  SHARED: {len(shared)} → {sorted(shared)}")
                    _log(f"  ONLY User {u1}: {len(only_u1)} → {sorted(only_u1)}")
                    _log(f"  ONLY User {u2}: {len(only_u2)} → {sorted(only_u2)}")

                # Install apps per-user using push + pm install --user
                total_installs = sum(len(apps) for apps in user_app_sets.values())
                total_steps = total_installs + 2
                current_step = 0

                for user in device_users:
                    uid = int(user['id'])
                    uid_str = user['id']
                    user_apps = sorted(user_app_sets.get(uid_str, set()))

                    if not user_apps:
                        _log(f"\nUser {uid} ({user['name']}): no apps to install")
                        continue

                    _log(f"\n--- Installing {len(user_apps)} apps for User {uid} ({user['name']}) ---")

                    installed = 0
                    failed = 0
                    for pkg in user_apps:
                        self._check_cancel()
                        current_step += 1

                        apk_path = os.path.join(apps_dir, f"{pkg}.apk")
                        if not os.path.exists(apk_path):
                            _log(f"  SKIP {pkg} (APK not in backup)")
                            continue

                        if progress_callback:
                            progress_callback(current_step, total_steps, f"User {uid}: {pkg}")

                        # Use push + pm install --user for reliable per-user install
                        ok, output = self.adb.install_apk_for_user_via_push(serial, apk_path, uid)
                        if ok:
                            installed += 1
                            _log(f"  OK {pkg} → User {uid}")
                        else:
                            failed += 1
                            _log(f"  FAIL {pkg} → User {uid}: {output}")

                    _log(f"  User {uid} result: {installed} installed, {failed} failed")

                # Verify the result
                _log(f"\n--- VERIFICATION ---")
                for user in device_users:
                    uid = int(user['id'])
                    actual_apps = self.adb.get_user_packages(serial, user_id=uid)
                    expected = user_app_sets.get(user['id'], set())
                    _log(f"  User {uid} ({user['name']}): {len(actual_apps)} actual vs {len(expected)} expected")
                    _log(f"    Actual:   {sorted(actual_apps)}")
                    _log(f"    Expected: {sorted(expected)}")
                    extra = set(actual_apps) - expected
                    missing = expected - set(actual_apps)
                    if extra:
                        _log(f"    EXTRA (shouldn't be here): {sorted(extra)}")
                    if missing:
                        _log(f"    MISSING (should be here): {sorted(missing)}")
                    if not extra and not missing:
                        _log(f"    PERFECT MATCH!")

            else:
                # Standard single-user restore
                total_steps = len(apps_to_install) + 1
                current_step = 0

                for pkg in apps_to_install:
                    self._check_cancel()
                    current_step += 1

                    apk_path = os.path.join(apps_dir, f"{pkg}.apk")
                    if not os.path.exists(apk_path):
                        _log(f"Skipping {pkg} (APK not found)")
                        continue

                    _log(f"Installing: {pkg} ({current_step}/{len(apps_to_install)})")
                    if progress_callback:
                        progress_callback(current_step, total_steps, f"Installing {pkg}")

                    success = self.adb.install_apk(serial, apk_path)
                    if not success:
                        _log(f"WARNING: Failed to install {pkg}")

            # ── Restore per-user settings ──
            user_settings = manifest.get("user_settings", {})
            global_settings = manifest.get("global_settings", {})
            user_permissions = manifest.get("user_permissions", {})
            settings_applied = 0

            if user_settings or global_settings:
                _log("\n--- Restoring system settings ---")

                for user in device_users:
                    uid = int(user['id'])
                    uid_str = user['id']
                    u_settings = user_settings.get(uid_str, {})
                    if not u_settings:
                        continue

                    _log(f"Applying settings for User {uid} ({user['name']})...")
                    for ns in ("system", "secure"):
                        ns_settings = u_settings.get(ns, {})
                        for key, value in ns_settings.items():
                            self.adb.put_setting(serial, ns, key, value, user_id=uid)
                            settings_applied += 1
                        if ns_settings:
                            _log(f"  {ns}: {len(ns_settings)} settings applied")

                if global_settings:
                    _log("Applying global settings...")
                    for key, value in global_settings.items():
                        self.adb.put_setting(serial, "global", key, value)
                        settings_applied += 1
                    _log(f"  global: {len(global_settings)} settings applied")

            # ── Restore app permissions ──
            perms_granted = 0
            if user_permissions:
                _log("\n--- Restoring app permissions ---")
                for user in device_users:
                    uid = int(user['id'])
                    uid_str = user['id']
                    u_perms = user_permissions.get(uid_str, {})
                    if not u_perms:
                        continue
                    _log(f"Granting permissions for User {uid}...")
                    for pkg, perms in u_perms.items():
                        for perm in perms:
                            ok = self.adb.grant_permission(serial, pkg, perm, uid)
                            if ok:
                                perms_granted += 1
                    _log(f"  {perms_granted} permissions granted")

            current_step = total_steps
            if progress_callback:
                progress_callback(current_step, total_steps, "Done")

            _log(
                f"\nRestore complete!\n"
                f"Apps installed, {settings_applied} settings applied, "
                f"{perms_granted} permissions granted.\n"
                f"Diagnostic log saved to: {log_path}"
            )

            return True

        finally:
            diag_log.close()
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
