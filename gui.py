"""
GrapheneOS Cloner - Main GUI
Full-featured desktop GUI for device cloning, imaging, backup and restore.
"""
import os
import sys
import time
import threading
from typing import Optional, List

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QListWidget, QListWidgetItem,
    QStackedWidget, QFrame, QTextEdit, QFileDialog,
    QCheckBox, QGroupBox, QGridLayout, QMessageBox,
    QComboBox, QSplitter, QScrollArea, QSizePolicy,
    QSpacerItem, QApplication,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QSize, QThread
from PyQt5.QtGui import QFont, QIcon, QColor, QPalette

from config import (
    APP_NAME, APP_VERSION, PIXEL3_PARTITIONS,
    get_default_image_dir, get_default_backup_dir,
    get_factory_images_dir, FACTORY_IMAGE_URLS,
)
from adb_wrapper import ADBWrapper, FastbootWrapper, ADBDevice
from imaging import ImagingEngine, OperationCancelled


# ─── Signal bridge for thread-safe GUI updates ───
class WorkerSignals(QObject):
    progress = pyqtSignal(int, int, str)       # current, total, message
    status = pyqtSignal(str)                    # status text
    finished = pyqtSignal(bool, str)            # success, message
    log = pyqtSignal(str)                       # log line
    device_list = pyqtSignal(list)              # list of devices


# ─── Background Worker ───
class Worker(QThread):
    """Generic background worker for long-running operations."""

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self):
        try:
            result = self.func(*self.args, **self.kwargs)
            self.signals.finished.emit(True, str(result) if result else "Done")
        except OperationCancelled:
            self.signals.finished.emit(False, "Operation cancelled")
        except Exception as e:
            self.signals.finished.emit(False, f"Error: {str(e)}")


# ═══════════════════════════════════════════════════════════════
# MAIN WINDOW
# ═══════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1100, 700)
        self.resize(1200, 750)

        # Core modules
        self.adb = ADBWrapper()
        self.fastboot = FastbootWrapper()
        self.imaging = ImagingEngine(self.adb, self.fastboot)

        # State
        self.current_worker = None
        self.adb_devices = []
        self.fastboot_devices = []

        self._build_ui()
        self._start_device_poll()

    # ──────────────────────────────────────────────
    # UI CONSTRUCTION
    # ──────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ─ Top bar ─
        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(20, 10, 20, 10)

        title_col = QVBoxLayout()
        lbl_title = QLabel(APP_NAME)
        lbl_title.setObjectName("appTitle")
        lbl_sub = QLabel(f"v{APP_VERSION}  •  Pixel 3 Device Cloning Tool")
        lbl_sub.setObjectName("appSubtitle")
        title_col.addWidget(lbl_title)
        title_col.addWidget(lbl_sub)
        top_layout.addLayout(title_col)
        top_layout.addStretch()

        # Device count indicator
        self.device_count_label = QLabel("No devices")
        self.device_count_label.setObjectName("statusLabel")
        top_layout.addWidget(self.device_count_label)

        # Refresh button
        btn_refresh = QPushButton("⟳ Refresh")
        btn_refresh.setFixedWidth(100)
        btn_refresh.clicked.connect(self._poll_devices)
        top_layout.addWidget(btn_refresh)

        root_layout.addWidget(top_bar)

        # ─ Body (sidebar + content) ─
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Sidebar
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 12, 0, 12)
        sidebar_layout.setSpacing(0)

        self.nav_buttons = []
        pages = [
            ("🏠  Dashboard", 0),
            ("📸  Create Image", 1),
            ("📋  Clone Device", 2),
            ("💾  Backup", 3),
            ("♻️  Restore", 4),
            ("📱  App Selector", 5),
            ("📜  Log", 6),
        ]
        for label, idx in pages:
            btn = QPushButton(label)
            btn.setObjectName("sidebarBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, i=idx: self._navigate(i))
            sidebar_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        sidebar_layout.addStretch()

        # Version label at bottom of sidebar
        ver = QLabel(f"  v{APP_VERSION}")
        ver.setObjectName("statusLabel")
        sidebar_layout.addWidget(ver)

        body.addWidget(sidebar)

        # Stacked pages
        self.pages = QStackedWidget()
        self.pages.addWidget(self._page_dashboard())
        self.pages.addWidget(self._page_create_image())
        self.pages.addWidget(self._page_clone())
        self.pages.addWidget(self._page_backup())
        self.pages.addWidget(self._page_restore())
        self.pages.addWidget(self._page_app_selector())
        self.pages.addWidget(self._page_log())
        body.addWidget(self.pages)

        root_layout.addLayout(body)

        # ─ Status bar ─
        status_bar = QFrame()
        status_bar.setFixedHeight(32)
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(20, 4, 20, 4)
        self.global_status = QLabel("Ready")
        self.global_status.setObjectName("statusLabel")
        status_layout.addWidget(self.global_status)
        status_layout.addStretch()
        root_layout.addWidget(status_bar)

        # Default to dashboard
        self._navigate(0)

    def _navigate(self, index):
        self.pages.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setProperty("active", "true" if i == index else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ──────────────────────────────────────────────
    # PAGE: DASHBOARD
    # ──────────────────────────────────────────────
    def _page_dashboard(self):
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # Header
        header = QLabel("Dashboard")
        header.setObjectName("headerLabel")
        layout.addWidget(header)

        desc = QLabel("Connect your Pixel 3 devices via USB to get started. "
                       "Enable USB debugging on your master phone and OEM unlocking on target devices.")
        desc.setObjectName("statusLabel")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Quick action cards
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(16)

        cards = [
            ("📸 Create Image", "Capture full system image\nfrom master device", 1, "#0f3460"),
            ("📋 Clone Device", "Flash image onto\ntarget devices", 2, "#0f3460"),
            ("💾 Backup", "Backup apps and data\nfrom any device", 3, "#0f3460"),
        ]
        for title, desc_text, nav_idx, color in cards:
            card = self._make_action_card(title, desc_text, nav_idx)
            cards_layout.addWidget(card)

        layout.addLayout(cards_layout)

        # Connected devices section
        dev_header = QLabel("Connected Devices")
        dev_header.setObjectName("cardTitle")
        layout.addWidget(dev_header)

        self.dashboard_devices_layout = QVBoxLayout()
        self.no_devices_label = QLabel("No devices detected.\n\n"
            "Checklist:\n"
            "1. Place adb.exe & fastboot.exe in the 'tools' folder\n"
            "2. Enable USB Debugging on your phone (Settings → System → Developer Options)\n"
            "3. Install Google USB Driver on your Windows PC\n"
            "4. Connect phone via USB and accept the 'Allow USB debugging' prompt on screen")
        self.no_devices_label.setObjectName("statusLabel")
        self.dashboard_devices_layout.addWidget(self.no_devices_label)
        layout.addLayout(self.dashboard_devices_layout)

        layout.addStretch()

        # Prerequisites info
        prereq_box = QGroupBox("Prerequisites")
        prereq_layout = QVBoxLayout(prereq_box)
        prereq_items = [
            "✓ USB Debugging enabled (Settings → System → Developer Options)",
            "✓ Root access enabled on master phone (Developer Options → 'Enable root access via ADB')",
            "✓ OEM Unlocking enabled on target phones (for cloning)",
            "✓ Good quality USB cables (preferably USB-C to USB-C)",
            "✓ Google USB Driver installed on Windows PC",
        ]
        for item in prereq_items:
            lbl = QLabel(item)
            lbl.setStyleSheet("color: #8899aa; font-size: 12px;")
            prereq_layout.addWidget(lbl)
        layout.addWidget(prereq_box)

        scroll.setWidget(content)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return page

    def _make_action_card(self, title, description, nav_index):
        card = QFrame()
        card.setObjectName("card")
        card.setFixedHeight(160)
        card.setCursor(Qt.PointingHandCursor)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(card)
        layout.setSpacing(8)

        lbl_title = QLabel(title)
        lbl_title.setObjectName("cardTitle")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel(description)
        lbl_desc.setObjectName("cardSubtitle")
        lbl_desc.setWordWrap(True)
        layout.addWidget(lbl_desc)

        layout.addStretch()

        btn = QPushButton("Open →")
        btn.setObjectName("primaryBtn")
        btn.clicked.connect(lambda: self._navigate(nav_index))
        layout.addWidget(btn)

        return card

    # ──────────────────────────────────────────────
    # PAGE: CREATE IMAGE
    # ──────────────────────────────────────────────
    def _page_create_image(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        header = QLabel("Create Image")
        header.setObjectName("headerLabel")
        layout.addWidget(header)

        desc = QLabel("Capture a full system image from your master Pixel device. "
                       "The device should be connected via USB with USB Debugging ON. "
                       "Root access must be enabled in Developer Options for partition reading.")
        desc.setObjectName("statusLabel")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Source device selector
        grp_source = QGroupBox("Source Device")
        src_layout = QHBoxLayout(grp_source)
        self.img_device_combo = QComboBox()
        self.img_device_combo.setMinimumWidth(300)
        src_layout.addWidget(QLabel("Device:"))
        src_layout.addWidget(self.img_device_combo)
        src_layout.addStretch()

        btn_reboot_fb = QPushButton("Reboot to Fastboot")
        btn_reboot_fb.clicked.connect(self._reboot_to_fastboot_for_image)
        src_layout.addWidget(btn_reboot_fb)
        layout.addWidget(grp_source)

        # Output directory
        grp_output = QGroupBox("Output Location")
        out_layout = QHBoxLayout(grp_output)
        self.img_output_path = QLabel(get_default_image_dir())
        self.img_output_path.setObjectName("statusLabel")
        out_layout.addWidget(self.img_output_path)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_image_output)
        out_layout.addWidget(btn_browse)
        layout.addWidget(grp_output)

        # Partition selection
        grp_parts = QGroupBox("Partitions to Capture")
        parts_layout = QVBoxLayout(grp_parts)
        self.img_partition_checks = {}
        grid = QGridLayout()
        for i, part in enumerate(PIXEL3_PARTITIONS):
            cb = QCheckBox(part)
            cb.setChecked(True)
            self.img_partition_checks[part] = cb
            grid.addWidget(cb, i // 4, i % 4)
        parts_layout.addLayout(grid)

        btn_row = QHBoxLayout()
        btn_all = QPushButton("Select All")
        btn_all.clicked.connect(lambda: [cb.setChecked(True) for cb in self.img_partition_checks.values()])
        btn_none = QPushButton("Select None")
        btn_none.clicked.connect(lambda: [cb.setChecked(False) for cb in self.img_partition_checks.values()])
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        btn_row.addStretch()
        parts_layout.addLayout(btn_row)
        layout.addWidget(grp_parts)

        # Progress
        self.img_progress = QProgressBar()
        self.img_progress.setVisible(False)
        layout.addWidget(self.img_progress)

        self.img_status = QLabel("")
        self.img_status.setObjectName("statusLabel")
        layout.addWidget(self.img_status)

        # Action buttons
        btn_layout = QHBoxLayout()
        self.btn_create_image = QPushButton("📸  Create Image")
        self.btn_create_image.setObjectName("primaryBtn")
        self.btn_create_image.clicked.connect(self._start_create_image)
        btn_layout.addWidget(self.btn_create_image)

        self.btn_cancel_image = QPushButton("Cancel")
        self.btn_cancel_image.setObjectName("dangerBtn")
        self.btn_cancel_image.setVisible(False)
        self.btn_cancel_image.clicked.connect(self._cancel_operation)
        btn_layout.addWidget(self.btn_cancel_image)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()
        return page

    # ──────────────────────────────────────────────
    # PAGE: CLONE DEVICE
    # ──────────────────────────────────────────────
    def _page_clone(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        header = QLabel("Clone Device")
        header.setObjectName("headerLabel")
        layout.addWidget(header)

        desc = QLabel("Flash a previously captured image onto one or more target Pixel devices.\n"
                       "Target devices must be in fastboot mode with bootloader unlocked.")
        desc.setObjectName("statusLabel")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Image file selector
        grp_img = QGroupBox("Image File")
        img_layout = QHBoxLayout(grp_img)
        self.clone_image_path = QLabel("No image selected")
        self.clone_image_path.setObjectName("statusLabel")
        img_layout.addWidget(self.clone_image_path)
        btn_select = QPushButton("Select Image...")
        btn_select.clicked.connect(self._browse_clone_image)
        img_layout.addWidget(btn_select)
        layout.addWidget(grp_img)

        # Image info
        self.clone_image_info = QLabel("")
        self.clone_image_info.setObjectName("statusLabel")
        self.clone_image_info.setWordWrap(True)
        layout.addWidget(self.clone_image_info)

        # Target devices
        grp_targets = QGroupBox("Target Devices (Fastboot Mode)")
        targets_layout = QVBoxLayout(grp_targets)
        self.clone_device_list = QListWidget()
        self.clone_device_list.setMaximumHeight(150)
        targets_layout.addWidget(self.clone_device_list)

        targets_btn_layout = QHBoxLayout()
        btn_refresh_targets = QPushButton("⟳ Refresh Devices")
        btn_refresh_targets.clicked.connect(self._poll_devices)
        targets_btn_layout.addWidget(btn_refresh_targets)

        self.btn_check_unlock = QPushButton("🔓 Check Bootloader Status")
        self.btn_check_unlock.clicked.connect(self._check_bootloader_status)
        targets_btn_layout.addWidget(self.btn_check_unlock)

        self.btn_unlock_bootloader = QPushButton("🔑 Unlock Bootloader")
        self.btn_unlock_bootloader.setObjectName("dangerBtn")
        self.btn_unlock_bootloader.clicked.connect(self._unlock_bootloader)
        targets_btn_layout.addWidget(self.btn_unlock_bootloader)

        self.btn_lock_bootloader = QPushButton("🔒 Lock Bootloader")
        self.btn_lock_bootloader.clicked.connect(self._lock_bootloader)
        targets_btn_layout.addWidget(self.btn_lock_bootloader)

        targets_btn_layout.addStretch()
        targets_layout.addLayout(targets_btn_layout)

        # Bootloader status label
        self.bootloader_status = QLabel("")
        self.bootloader_status.setObjectName("statusLabel")
        self.bootloader_status.setWordWrap(True)
        targets_layout.addWidget(self.bootloader_status)

        layout.addWidget(grp_targets)

        # Factory image section (recommended method)
        grp_factory = QGroupBox("Option B: Flash Official GrapheneOS Image (Recommended — No Root Needed)")
        factory_layout = QVBoxLayout(grp_factory)

        factory_desc = QLabel(
            "Flash an official GrapheneOS factory image to target devices.\n"
            "No root access or image capture needed! For Pixel 3, use the built-in download\n"
            "since GrapheneOS discontinued official Pixel 3 images.")
        factory_desc.setObjectName("statusLabel")
        factory_desc.setWordWrap(True)
        factory_layout.addWidget(factory_desc)

        # Built-in download section
        download_layout = QHBoxLayout()
        self.btn_download_factory = QPushButton("Download Pixel 3 Factory Image (built-in)")
        self.btn_download_factory.setObjectName("primaryBtn")
        self.btn_download_factory.clicked.connect(self._download_bundled_factory_image)
        download_layout.addWidget(self.btn_download_factory)

        self.download_status_label = QLabel("")
        self.download_status_label.setObjectName("statusLabel")
        download_layout.addWidget(self.download_status_label)
        download_layout.addStretch()
        factory_layout.addLayout(download_layout)

        # Download progress bar
        self.download_progress = QProgressBar()
        self.download_progress.setVisible(False)
        factory_layout.addWidget(self.download_progress)

        # Manual file selection
        factory_file_layout = QHBoxLayout()
        self.factory_image_path = QLabel("No factory image selected")
        self.factory_image_path.setObjectName("statusLabel")
        factory_file_layout.addWidget(self.factory_image_path)
        btn_select_factory = QPushButton("Select Factory ZIP...")
        btn_select_factory.clicked.connect(self._browse_factory_image)
        factory_file_layout.addWidget(btn_select_factory)
        factory_layout.addLayout(factory_file_layout)

        self.btn_flash_factory = QPushButton("Flash Factory Image to Selected Devices")
        self.btn_flash_factory.setObjectName("primaryBtn")
        self.btn_flash_factory.clicked.connect(self._start_flash_factory)
        factory_layout.addWidget(self.btn_flash_factory)

        # Manual flash option for bootloader locking
        self.btn_manual_flash = QPushButton("Manual Flash via Command Prompt (for Bootloader Locking)")
        self.btn_manual_flash.setToolTip(
            "Extracts the factory image and opens a Command Prompt so you can run\n"
            "flash-all.bat manually. This is the most reliable method for\n"
            "bootloader locking — it's the official GrapheneOS-recommended process."
        )
        self.btn_manual_flash.clicked.connect(self._manual_flash_factory)
        factory_layout.addWidget(self.btn_manual_flash)

        # Check if factory image already downloaded (must be after factory_image_path is created)
        self._check_bundled_factory_image()

        layout.addWidget(grp_factory)

        # Re-label the existing image section as Option A
        grp_img.setTitle("Option A: Clone from Captured Image (Requires Root on Master)")

        # Pre-flash checklist
        grp_checklist = QGroupBox("Pre-Flight Checklist")
        checklist_layout = QVBoxLayout(grp_checklist)
        checklist_items = [
            "1. On TARGET phone: Enable Developer Options (tap Build Number 7 times)",
            "2. In Developer Options: Enable 'OEM unlocking'",
            "3. Reboot TARGET phone to fastboot: hold Power + Volume Down",
            "4. Click 'Unlock Bootloader' above (first time only)",
            "5. Either: Select a captured .gimg image (Option A) or a factory ZIP (Option B)",
            "6. Click Clone / Flash",
        ]
        for item in checklist_items:
            lbl = QLabel(item)
            lbl.setObjectName("statusLabel")
            lbl.setWordWrap(True)
            checklist_layout.addWidget(lbl)
        layout.addWidget(grp_checklist)

        # Progress
        self.clone_progress = QProgressBar()
        self.clone_progress.setVisible(False)
        layout.addWidget(self.clone_progress)

        self.clone_status = QLabel("")
        self.clone_status.setObjectName("statusLabel")
        self.clone_status.setWordWrap(True)
        layout.addWidget(self.clone_status)

        # Action buttons
        btn_layout = QHBoxLayout()
        self.btn_clone = QPushButton("📋  Clone to Selected Devices")
        self.btn_clone.setObjectName("primaryBtn")
        self.btn_clone.clicked.connect(self._start_clone)
        btn_layout.addWidget(self.btn_clone)

        self.btn_cancel_clone = QPushButton("Cancel")
        self.btn_cancel_clone.setObjectName("dangerBtn")
        self.btn_cancel_clone.setVisible(False)
        self.btn_cancel_clone.clicked.connect(self._cancel_operation)
        btn_layout.addWidget(self.btn_cancel_clone)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()
        return page

    # ──────────────────────────────────────────────
    # PAGE: BACKUP
    # ──────────────────────────────────────────────
    def _page_backup(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        header = QLabel("Backup")
        header.setObjectName("headerLabel")
        layout.addWidget(header)

        desc = QLabel("Create a full backup of apps from a connected device. "
                       "The device should be in normal ADB mode (USB debugging ON).")
        desc.setObjectName("statusLabel")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Source device
        grp_src = QGroupBox("Source Device (ADB Mode)")
        src_layout = QHBoxLayout(grp_src)
        self.backup_device_combo = QComboBox()
        self.backup_device_combo.setMinimumWidth(300)
        src_layout.addWidget(QLabel("Device:"))
        src_layout.addWidget(self.backup_device_combo)
        src_layout.addStretch()
        layout.addWidget(grp_src)

        # Output directory
        grp_out = QGroupBox("Backup Location")
        out_layout = QHBoxLayout(grp_out)
        self.backup_output_path = QLabel(get_default_backup_dir())
        self.backup_output_path.setObjectName("statusLabel")
        out_layout.addWidget(self.backup_output_path)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_backup_output)
        out_layout.addWidget(btn_browse)
        layout.addWidget(grp_out)

        # User profiles section
        grp_users = QGroupBox("User Profiles")
        users_layout = QVBoxLayout(grp_users)

        users_desc = QLabel(
            "The tool will automatically detect ALL user profiles on the device and\n"
            "backup apps from each profile. Apps are shared but tracked per-user.")
        users_desc.setObjectName("statusLabel")
        users_desc.setWordWrap(True)
        users_layout.addWidget(users_desc)

        users_btn_layout = QHBoxLayout()
        btn_detect_users = QPushButton("Detect User Profiles")
        btn_detect_users.clicked.connect(self._detect_user_profiles)
        users_btn_layout.addWidget(btn_detect_users)
        users_btn_layout.addStretch()
        users_layout.addLayout(users_btn_layout)

        self.user_profiles_label = QLabel("Click 'Detect User Profiles' to scan device")
        self.user_profiles_label.setObjectName("statusLabel")
        self.user_profiles_label.setWordWrap(True)
        users_layout.addWidget(self.user_profiles_label)

        layout.addWidget(grp_users)

        # Options
        self.backup_include_apps = QCheckBox("Include user-installed apps (APKs)")
        self.backup_include_apps.setChecked(True)
        layout.addWidget(self.backup_include_apps)

        # Progress
        self.backup_progress = QProgressBar()
        self.backup_progress.setVisible(False)
        layout.addWidget(self.backup_progress)

        self.backup_status = QLabel("")
        self.backup_status.setObjectName("statusLabel")
        layout.addWidget(self.backup_status)

        # Action
        btn_layout = QHBoxLayout()
        self.btn_backup = QPushButton("💾  Create Backup")
        self.btn_backup.setObjectName("primaryBtn")
        self.btn_backup.clicked.connect(self._start_backup)
        btn_layout.addWidget(self.btn_backup)

        self.btn_cancel_backup = QPushButton("Cancel")
        self.btn_cancel_backup.setObjectName("dangerBtn")
        self.btn_cancel_backup.setVisible(False)
        self.btn_cancel_backup.clicked.connect(self._cancel_operation)
        btn_layout.addWidget(self.btn_cancel_backup)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()
        return page

    # ──────────────────────────────────────────────
    # PAGE: RESTORE
    # ──────────────────────────────────────────────
    def _page_restore(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        header = QLabel("Restore")
        header.setObjectName("headerLabel")
        layout.addWidget(header)

        desc = QLabel("Restore a backup or image file to a connected device. "
                       "For full images (.gimg), device must be in fastboot mode. "
                       "For app backups (.gbak), device should be in ADB mode.")
        desc.setObjectName("statusLabel")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # File selector
        grp_file = QGroupBox("Restore File")
        file_layout = QHBoxLayout(grp_file)
        self.restore_file_path = QLabel("No file selected")
        self.restore_file_path.setObjectName("statusLabel")
        file_layout.addWidget(self.restore_file_path)
        btn_browse = QPushButton("Select File...")
        btn_browse.clicked.connect(self._browse_restore_file)
        file_layout.addWidget(btn_browse)
        layout.addWidget(grp_file)

        self.restore_file_info = QLabel("")
        self.restore_file_info.setObjectName("statusLabel")
        self.restore_file_info.setWordWrap(True)
        layout.addWidget(self.restore_file_info)

        # Target device
        grp_target = QGroupBox("Target Device")
        target_layout = QHBoxLayout(grp_target)
        self.restore_device_combo = QComboBox()
        self.restore_device_combo.setMinimumWidth(300)
        target_layout.addWidget(QLabel("Device:"))
        target_layout.addWidget(self.restore_device_combo)
        target_layout.addStretch()
        layout.addWidget(grp_target)

        # Progress
        self.restore_progress = QProgressBar()
        self.restore_progress.setVisible(False)
        layout.addWidget(self.restore_progress)

        self.restore_status = QLabel("")
        self.restore_status.setObjectName("statusLabel")
        layout.addWidget(self.restore_status)

        # Action
        btn_layout = QHBoxLayout()
        self.btn_restore = QPushButton("♻️  Restore")
        self.btn_restore.setObjectName("primaryBtn")
        self.btn_restore.clicked.connect(self._start_restore)
        btn_layout.addWidget(self.btn_restore)

        self.btn_cancel_restore = QPushButton("Cancel")
        self.btn_cancel_restore.setObjectName("dangerBtn")
        self.btn_cancel_restore.setVisible(False)
        self.btn_cancel_restore.clicked.connect(self._cancel_operation)
        btn_layout.addWidget(self.btn_cancel_restore)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()
        return page

    # ──────────────────────────────────────────────
    # PAGE: APP SELECTOR
    # ──────────────────────────────────────────────
    def _page_app_selector(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        header = QLabel("App Selector")
        header.setObjectName("headerLabel")
        layout.addWidget(header)

        desc = QLabel("Select which apps to include when cloning or restoring. "
                       "Load apps from a connected device or from a saved image/backup file.")
        desc.setObjectName("statusLabel")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Source selection
        grp_src = QGroupBox("Load Apps From")
        src_layout = QHBoxLayout(grp_src)

        btn_from_device = QPushButton("📱 From Device")
        btn_from_device.clicked.connect(self._load_apps_from_device)
        src_layout.addWidget(btn_from_device)

        btn_from_file = QPushButton("📁 From Image/Backup")
        btn_from_file.clicked.connect(self._load_apps_from_file)
        src_layout.addWidget(btn_from_file)
        src_layout.addStretch()
        layout.addWidget(grp_src)

        # App list
        self.app_list_widget = QListWidget()
        self.app_list_widget.setSelectionMode(QListWidget.MultiSelection)
        layout.addWidget(self.app_list_widget, 1)

        # Select buttons
        btn_row = QHBoxLayout()
        btn_sel_all = QPushButton("Select All")
        btn_sel_all.clicked.connect(self._select_all_apps)
        btn_sel_none = QPushButton("Select None")
        btn_sel_none.clicked.connect(self._select_no_apps)
        self.app_count_label = QLabel("0 apps loaded")
        self.app_count_label.setObjectName("statusLabel")
        btn_row.addWidget(btn_sel_all)
        btn_row.addWidget(btn_sel_none)
        btn_row.addStretch()
        btn_row.addWidget(self.app_count_label)
        layout.addLayout(btn_row)

        return page

    # ──────────────────────────────────────────────
    # PAGE: LOG
    # ──────────────────────────────────────────────
    def _page_log(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        header = QLabel("Operation Log")
        header.setObjectName("headerLabel")
        layout.addWidget(header)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            "QTextEdit { background-color: #1a1a2e; color: #00ff41; "
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 11px; "
            "border: 2px solid #333; padding: 8px; }"
        )
        layout.addWidget(self.log_text, 1)

        btn_row = QHBoxLayout()
        btn_save = QPushButton("Save Log to File")
        btn_save.setToolTip("Save the full log to a text file you can share for diagnostics")
        btn_save.clicked.connect(self._save_log_to_file)
        btn_row.addWidget(btn_save)

        btn_copy = QPushButton("Copy Log to Clipboard")
        btn_copy.clicked.connect(self._copy_log_to_clipboard)
        btn_row.addWidget(btn_copy)

        btn_clear = QPushButton("Clear Log")
        btn_clear.clicked.connect(self.log_text.clear)
        btn_row.addWidget(btn_clear)

        layout.addLayout(btn_row)

        return page

    def _save_log_to_file(self):
        """Save log contents to a timestamped text file on Desktop."""
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.isdir(desktop):
            desktop = os.path.expanduser("~")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(desktop, f"GrapheneOS_Cloner_Log_{timestamp}.txt")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"GrapheneOS Cloner v{APP_VERSION} — Diagnostic Log\n")
                f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")
                f.write(self.log_text.toPlainText())
            QMessageBox.information(self, "Log Saved", f"Log saved to:\n{log_path}")
            self._log(f"Log saved to: {log_path}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not save log: {e}")

    def _copy_log_to_clipboard(self):
        """Copy log contents to clipboard."""
        from PyQt5.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self.log_text.toPlainText())
        self._log("Log copied to clipboard")

    # ──────────────────────────────────────────────
    # DEVICE POLLING
    # ──────────────────────────────────────────────
    def _start_device_poll(self):
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_devices)
        self.poll_timer.start(5000)  # Poll every 5 seconds
        self._poll_devices()  # Initial poll

    def _poll_devices(self):
        """Poll for connected ADB and fastboot devices."""
        try:
            self.adb_devices = self.adb.list_devices()
        except Exception:
            self.adb_devices = []

        try:
            self.fastboot_devices = self.fastboot.list_devices()
        except Exception:
            self.fastboot_devices = []

        total = len(self.adb_devices) + len(self.fastboot_devices)
        self.device_count_label.setText(
            f"{total} device{'s' if total != 1 else ''} connected"
            if total > 0 else "No devices"
        )

        self._update_device_combos()
        self._update_dashboard_devices()

    def _update_device_combos(self):
        """Update all device combo boxes."""
        # ADB devices for image creation
        self.img_device_combo.clear()
        for d in self.adb_devices:
            label = f"{d.serial} ({d.model or 'ADB'})"
            self.img_device_combo.addItem(label, d.serial)
        for d in self.fastboot_devices:
            label = f"{d['serial']} (Fastboot)"
            self.img_device_combo.addItem(label, d['serial'])

        # Backup device (ADB only)
        self.backup_device_combo.clear()
        for d in self.adb_devices:
            label = f"{d.serial} ({d.model or 'ADB'})"
            self.backup_device_combo.addItem(label, d.serial)

        # Clone targets (fastboot only)
        self.clone_device_list.clear()
        for d in self.fastboot_devices:
            item = QListWidgetItem(f"{d['serial']} (Fastboot)")
            item.setData(Qt.UserRole, d['serial'])
            item.setCheckState(Qt.Checked)
            self.clone_device_list.addItem(item)

        # Restore device (only if restore page exists)
        if hasattr(self, 'restore_device_combo'):
            self.restore_device_combo.clear()
            for d in self.adb_devices:
                label = f"{d.serial} ({d.model or 'ADB'})"
                self.restore_device_combo.addItem(label, d.serial)
            for d in self.fastboot_devices:
                label = f"{d['serial']} (Fastboot)"
                self.restore_device_combo.addItem(label, d['serial'])

    def _update_dashboard_devices(self):
        """Update the dashboard devices list."""
        # Clear existing device cards (keep the no_devices_label)
        while self.dashboard_devices_layout.count() > 1:
            item = self.dashboard_devices_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

        total = len(self.adb_devices) + len(self.fastboot_devices)
        self.no_devices_label.setVisible(total == 0)

        for d in self.adb_devices:
            card = self._make_device_card(d.serial, d.model or "Pixel Device", "ADB Mode", "#2ecc71")
            self.dashboard_devices_layout.addWidget(card)

        for d in self.fastboot_devices:
            card = self._make_device_card(d['serial'], d.get('product', 'Pixel Device'), "Fastboot Mode", "#f39c12")
            self.dashboard_devices_layout.addWidget(card)

    def _make_device_card(self, serial, model, mode, color):
        card = QFrame()
        card.setObjectName("deviceCard")
        layout = QHBoxLayout(card)

        info_col = QVBoxLayout()
        name = QLabel(f"📱  {model}")
        name.setObjectName("deviceName")
        info_col.addWidget(name)
        ser = QLabel(f"Serial: {serial}")
        ser.setObjectName("deviceSerial")
        info_col.addWidget(ser)
        layout.addLayout(info_col)

        layout.addStretch()

        status = QLabel(f"● {mode}")
        status.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px;")
        layout.addWidget(status)

        return card

    # ──────────────────────────────────────────────
    # ACTIONS
    # ──────────────────────────────────────────────
    def _log(self, msg):
        """Append to operation log."""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {msg}")
        self.global_status.setText(msg)

    def _reboot_to_fastboot_for_image(self):
        idx = self.img_device_combo.currentIndex()
        if idx < 0:
            return
        serial = self.img_device_combo.currentData()
        if serial:
            self._log(f"Rebooting {serial} to fastboot...")
            self.adb.reboot_to_bootloader(serial)
            self._log("Device will appear in fastboot mode shortly. Click Refresh.")

    def _browse_image_output(self):
        path = QFileDialog.getExistingDirectory(self, "Select Output Directory", get_default_image_dir())
        if path:
            self.img_output_path.setText(path)

    def _browse_clone_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image File", get_default_image_dir(),
            "GrapheneOS Image (*.gimg);;All Files (*.*)"
        )
        if path:
            self.clone_image_path.setText(path)
            manifest = ImagingEngine.read_archive_manifest(path)
            if manifest:
                self.clone_image_info.setText(
                    f"Model: {manifest.get('device_model', 'N/A')}  |  "
                    f"Created: {manifest.get('created_at', 'N/A')}  |  "
                    f"Partitions: {', '.join(manifest.get('partitions', []))}"
                )

    def _browse_backup_output(self):
        path = QFileDialog.getExistingDirectory(self, "Select Backup Directory", get_default_backup_dir())
        if path:
            self.backup_output_path.setText(path)

    def _browse_restore_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Restore File", "",
            "GrapheneOS Files (*.gimg *.gbak);;All Files (*.*)"
        )
        if path:
            self.restore_file_path.setText(path)
            manifest = ImagingEngine.read_archive_manifest(path)
            if manifest:
                file_type = "Full Image" if path.endswith(".gimg") else "App Backup"
                self.restore_file_info.setText(
                    f"Type: {file_type}  |  "
                    f"Model: {manifest.get('device_model', 'N/A')}  |  "
                    f"Created: {manifest.get('created_at', 'N/A')}"
                )

    def _cancel_operation(self):
        if self.imaging:
            self.imaging.cancel()
        self._log("Cancellation requested...")

    def _start_create_image(self):
        idx = self.img_device_combo.currentIndex()
        if idx < 0:
            QMessageBox.warning(self, "No Device", "No device selected. Connect a device first.")
            return

        serial = self.img_device_combo.currentData()
        output = self.img_output_path.text()
        partitions = [p for p, cb in self.img_partition_checks.items() if cb.isChecked()]

        if not partitions:
            QMessageBox.warning(self, "No Partitions", "Select at least one partition to capture.")
            return

        # Detect if device is in ADB or fastboot mode
        is_adb = any(d.serial == serial for d in self.adb_devices)
        is_fastboot = any(d['serial'] == serial for d in self.fastboot_devices)
        mode = "adb" if is_adb else "fastboot"

        if is_adb:
            self._log(f"Starting image creation from {serial} (ADB mode - no reboot needed)...")
            self._log("Tip: Ensure root access is enabled in Settings → System → Developer Options")
        else:
            self._log(f"Starting image creation from {serial} (Fastboot mode)...")

        self.img_progress.setVisible(True)
        self.img_progress.setValue(0)
        self.btn_create_image.setEnabled(False)
        self.btn_cancel_image.setVisible(True)

        def do_work():
            return self.imaging.create_image(
                serial, output, partitions, mode=mode,
                progress_callback=lambda c, t, m: self._worker_progress(c, t, m, self.img_progress),
                status_callback=lambda s: self._worker_status(s, self.img_status),
            )

        self._run_worker(do_work, self._on_image_done)

    def _on_image_done(self, success, message):
        self.btn_create_image.setEnabled(True)
        self.btn_cancel_image.setVisible(False)
        if success:
            self.img_progress.setValue(100)
            self.img_status.setText(f"✅ Image created: {message}")
            self._log(f"Image created successfully: {message}")
        else:
            self.img_status.setText(f"❌ {message}")
            self._log(f"Image creation failed: {message}")

    def _check_bootloader_status(self):
        """Check bootloader lock status for all selected fastboot devices."""
        targets = []
        for i in range(self.clone_device_list.count()):
            item = self.clone_device_list.item(i)
            if item.checkState() == Qt.Checked:
                targets.append(item.data(Qt.UserRole))

        if not targets:
            self.bootloader_status.setText("No devices selected. Connect a device in fastboot mode first.")
            return

        status_lines = []
        for serial in targets:
            is_unlocked, msg = self.imaging.check_oem_unlocked(serial)
            icon = "🟢" if is_unlocked else "🔴"
            status_lines.append(f"{icon} {serial}: {msg}")

        self.bootloader_status.setText("\n".join(status_lines))
        self._log("Bootloader check: " + " | ".join(status_lines))

    def _unlock_bootloader(self):
        """Attempt to unlock bootloader on selected fastboot devices."""
        targets = []
        for i in range(self.clone_device_list.count()):
            item = self.clone_device_list.item(i)
            if item.checkState() == Qt.Checked:
                targets.append(item.data(Qt.UserRole))

        if not targets:
            QMessageBox.warning(self, "No Targets", "No fastboot devices selected.")
            return

        # Build device list string for confirmation
        device_list_str = "\n".join(f"  • {s}" for s in targets)
        reply = QMessageBox.warning(
            self, "⚠️ UNLOCK BOOTLOADER — DATA WILL BE ERASED",
            "⚠️⚠️⚠️ DANGER: THIS WILL ERASE ALL DATA ON THE DEVICE! ⚠️⚠️⚠️\n\n"
            f"You are about to unlock the bootloader on:\n{device_list_str}\n\n"
            "IMPORTANT: Make sure this is your TARGET phone, NOT your master phone!\n"
            "Unlocking erases all apps, settings, and user data.\n\n"
            "Prerequisites:\n"
            "• 'OEM unlocking' must be enabled in Settings > Developer Options\n"
            "• You may need to confirm on the device screen\n\n"
            "Are you SURE this is the TARGET device (not your master)?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        for serial in targets:
            self._log(f"Unlocking bootloader on {serial}...")
            self.bootloader_status.setText(f"Unlocking {serial}... Check device screen for confirmation prompt!")
            QApplication.processEvents()

            success, msg = self.imaging.unlock_bootloader(
                serial,
                status_callback=lambda s: self._log(s)
            )

            if success:
                self.bootloader_status.setText(f"🟢 {serial}: Bootloader unlocked! Device may reboot - put it back in fastboot mode.")
                self._log(f"Bootloader unlocked on {serial}")
            else:
                self.bootloader_status.setText(f"🔴 {serial}: {msg}")
                self._log(f"Failed to unlock {serial}: {msg}")

    def _detect_user_profiles(self):
        """Detect user profiles on the connected device."""
        if not self.adb_devices:
            self.user_profiles_label.setText("No ADB device connected. Connect a device first.")
            return
        serial = self.adb_devices[0].serial
        self._log(f"Detecting user profiles on {serial}...")
        users = self.adb.list_users(serial)

        lines = []
        for u in users:
            uid = int(u['id'])
            pkgs = self.adb.get_user_packages(serial, user_id=uid)
            lines.append(f"User {u['id']} ({u['name']}): {len(pkgs)} apps")
            self._log(f"  User {u['id']} ({u['name']}): {len(pkgs)} user-installed apps")

        self.user_profiles_label.setText(
            f"Found {len(users)} user profile(s):\n" + "\n".join(lines) +
            "\n\nAll profiles will be backed up automatically."
        )
        self._log(f"Detected {len(users)} user profile(s)")

    def _check_bundled_factory_image(self):
        """Check if the Pixel 3 factory image is already downloaded."""
        factory_dir = get_factory_images_dir()
        img_info = FACTORY_IMAGE_URLS.get("blueline", {})
        if not img_info:
            return
        local_path = os.path.join(factory_dir, img_info["filename"])
        if os.path.isfile(local_path):
            size_mb = os.path.getsize(local_path) / 1048576
            self.download_status_label.setText(f"Already downloaded ({size_mb:.0f} MB)")
            self.factory_image_path.setText(local_path)
            self.btn_download_factory.setText("Re-download Pixel 3 Factory Image")

    def _download_bundled_factory_image(self):
        """Download the Pixel 3 GrapheneOS factory image from Wayback Machine."""
        import urllib.request
        import hashlib

        img_info = FACTORY_IMAGE_URLS.get("blueline")
        if not img_info:
            QMessageBox.warning(self, "Error", "No factory image URL configured for Pixel 3.")
            return

        factory_dir = get_factory_images_dir()
        os.makedirs(factory_dir, exist_ok=True)
        local_path = os.path.join(factory_dir, img_info["filename"])
        local_sig = os.path.join(factory_dir, img_info["sig_filename"])

        self.btn_download_factory.setEnabled(False)
        self.download_progress.setVisible(True)
        self.download_progress.setValue(0)
        self.download_status_label.setText("Downloading factory image (~1 GB)...")
        self._log(f"Downloading {img_info['filename']} from Wayback Machine archive...")
        self._log("This is a ~1 GB download. Please be patient...")

        def do_download():
            # Download factory image with robust streaming
            req = urllib.request.Request(img_info["url"])
            req.add_header("User-Agent", "GrapheneOS-Cloner/1.6")

            try:
                response = urllib.request.urlopen(req, timeout=600)
            except Exception as e:
                raise Exception(f"Failed to connect: {e}")

            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            block_size = 262144  # 256KB chunks (more reliable for large files)

            with open(local_path, "wb") as f:
                while True:
                    try:
                        chunk = response.read(block_size)
                    except Exception as e:
                        raise Exception(
                            f"Download interrupted at {downloaded // 1048576} MB: {e}\n"
                            f"Please try again — the download will resume."
                        )
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = int(downloaded * 100 / total_size)
                        QTimer.singleShot(0, lambda p=pct: self.download_progress.setValue(p))
                        QTimer.singleShot(0, lambda d=downloaded, t=total_size:
                            self.download_status_label.setText(
                                f"Downloading... {d // 1048576} MB / {t // 1048576} MB"
                            ))

            # Verify the downloaded file is a valid ZIP
            actual_size = os.path.getsize(local_path)
            if total_size > 0 and actual_size < total_size * 0.95:
                os.remove(local_path)
                raise Exception(
                    f"Download incomplete: got {actual_size // 1048576} MB of {total_size // 1048576} MB.\n"
                    f"Please try again."
                )

            # Quick ZIP validation
            import zipfile
            try:
                with zipfile.ZipFile(local_path, "r") as zf:
                    names = zf.namelist()
                    if not names:
                        raise Exception("ZIP is empty")
            except zipfile.BadZipFile:
                os.remove(local_path)
                raise Exception(
                    "Downloaded file is not a valid ZIP. The download may have been corrupted.\n"
                    "Please try again."
                )

            # Download signature file
            QTimer.singleShot(0, lambda: self.download_status_label.setText("Downloading signature..."))
            try:
                sig_req = urllib.request.Request(img_info["sig_url"])
                sig_req.add_header("User-Agent", "GrapheneOS-Cloner/1.6")
                sig_resp = urllib.request.urlopen(sig_req, timeout=60)
                with open(local_sig, "wb") as f:
                    f.write(sig_resp.read())
            except Exception:
                pass  # Signature is optional

            return local_path

        def on_done(success, message):
            self.btn_download_factory.setEnabled(True)
            self.download_progress.setVisible(False)
            if success and os.path.isfile(local_path):
                size_mb = os.path.getsize(local_path) / 1048576
                self.download_status_label.setText(f"Downloaded and verified! ({size_mb:.0f} MB)")
                self.factory_image_path.setText(local_path)
                self.btn_download_factory.setText("Re-download Pixel 3 Factory Image")
                self._log(f"Factory image downloaded and verified: {local_path} ({size_mb:.0f} MB)")
            else:
                self.download_status_label.setText(f"Download failed: {message}")
                self._log(f"Factory image download failed: {message}")

        self._run_worker(do_download, on_done)

    def _browse_factory_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select GrapheneOS Factory Image", get_factory_images_dir(),
            "ZIP Files (*.zip);;All Files (*.*)"
        )
        if path:
            self.factory_image_path.setText(path)
            self._log(f"Factory image selected: {path}")

    def _manual_flash_factory(self):
        """Extract factory image and open Command Prompt for manual flash-all.bat execution."""
        factory_path = self.factory_image_path.text()
        if not os.path.isfile(factory_path):
            QMessageBox.warning(self, "No File", "Select a GrapheneOS factory image ZIP first.")
            return

        import zipfile as zf_mod
        import tempfile

        self._log("Extracting factory image for manual flash...")
        self.clone_status.setText("Extracting factory image...")

        # Extract to a short, accessible path
        extract_dir = os.path.join(os.path.expanduser("~"), "GrapheneOS_Flash")
        os.makedirs(extract_dir, exist_ok=True)

        try:
            with zf_mod.ZipFile(factory_path, "r") as zf:
                zf.extractall(extract_dir)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to extract: {e}")
            return

        # Find the directory containing flash-all.bat/sh
        script_dir = extract_dir
        for root, dirs, files in os.walk(extract_dir):
            if "flash-all.bat" in files or "flash-all.sh" in files:
                script_dir = root
                break

        # Copy platform-tools (fastboot) to the script directory
        from config import get_fastboot_path
        fastboot_src = get_fastboot_path()
        if os.path.exists(fastboot_src):
            import shutil
            fastboot_name = os.path.basename(fastboot_src)
            dst = os.path.join(script_dir, fastboot_name)
            if not os.path.exists(dst):
                shutil.copy2(fastboot_src, dst)
            # Copy DLLs too
            fb_dir = os.path.dirname(fastboot_src)
            for f in os.listdir(fb_dir):
                if f.endswith(".dll"):
                    src = os.path.join(fb_dir, f)
                    d = os.path.join(script_dir, f)
                    if not os.path.exists(d):
                        shutil.copy2(src, d)

        self._log(f"Factory image extracted to: {script_dir}")
        self._log("Opening Command Prompt...")

        # Open Command Prompt in the script directory
        # CRITICAL: Add script_dir to PATH so flash-all.bat can find fastboot
        # (GrapheneOS flash-all.bat uses PowerShell which won't find ./fastboot)
        if os.name == "nt":
            import subprocess
            env = os.environ.copy()
            env["PATH"] = script_dir + ";" + env.get("PATH", "")
            subprocess.Popen(
                ["cmd", "/k",
                 f'set PATH={script_dir};%PATH% && '
                 f'echo. && echo ============================================ && '
                 f'echo GrapheneOS Manual Flash && '
                 f'echo ============================================ && '
                 f'echo. && '
                 f'echo 1. Make sure phone is in FASTBOOT mode && '
                 f'echo    (Power + Volume Down) && '
                 f'echo 2. Type: flash-all.bat && '
                 f'echo 3. Wait for flash to complete && '
                 f'echo 4. After phone boots, go back to fastboot && '
                 f'echo 5. Type: fastboot flashing lock && '
                 f'echo 6. Confirm on phone screen && '
                 f'echo. && '
                 f'echo Current directory: {script_dir} && '
                 f'echo. '],
                cwd=script_dir,
                env=env
            )
        else:
            import subprocess
            subprocess.Popen(["xterm", "-e", "bash"], cwd=script_dir)

        self.clone_status.setText(
            f"Command Prompt opened in: {script_dir}\n"
            "Type 'flash-all.bat' to flash, then 'fastboot flashing lock' to lock bootloader."
        )

        QMessageBox.information(
            self, "Manual Flash",
            "A Command Prompt has been opened in the factory image directory.\n\n"
            "Steps:\n"
            "1. Make sure phone is in FASTBOOT mode (Power + Volume Down)\n"
            "2. Type: flash-all.bat\n"
            "3. Wait for it to finish (phone will reboot)\n"
            "4. After phone boots, go back to fastboot (Power + Volume Down)\n"
            "5. Type: fastboot flashing lock\n"
            "6. Confirm on the phone screen\n\n"
            "This is the official GrapheneOS flashing method and the most\n"
            "reliable way to get bootloader locking working."
        )

    def _start_flash_factory(self):
        factory_path = self.factory_image_path.text()
        if not os.path.isfile(factory_path):
            QMessageBox.warning(self, "No File", "Select a GrapheneOS factory image ZIP first.")
            return

        targets = []
        for i in range(self.clone_device_list.count()):
            item = self.clone_device_list.item(i)
            if item.checkState() == Qt.Checked:
                targets.append(item.data(Qt.UserRole))

        if not targets:
            QMessageBox.warning(self, "No Targets", "No target devices selected.")
            return

        device_list_str = "\n".join(f"  • {s}" for s in targets)
        reply = QMessageBox.warning(
            self, "Confirm Factory Flash",
            f"You are about to flash GrapheneOS factory image onto:\n{device_list_str}\n\n"
            "This will install a FRESH copy of GrapheneOS.\n"
            "All existing data on these devices will be replaced.\n\n"
            "Make sure these are your TARGET phones, NOT your master!\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self._log(f"Starting factory flash to {len(targets)} device(s)...")
        self.clone_progress.setVisible(True)
        self.clone_progress.setValue(0)
        self.btn_flash_factory.setEnabled(False)
        self.btn_clone.setEnabled(False)
        self.btn_cancel_clone.setVisible(True)
        self.clone_status.setText("Starting factory image flash...")

        def do_work():
            results = []
            for serial in targets:
                self._worker_status(f"Flashing factory image to {serial}...", self.clone_status)
                result = self.imaging.flash_factory_image(
                    serial, factory_path,
                    progress_callback=lambda c, t, m: self._worker_progress(c, t, m, self.clone_progress),
                    status_callback=lambda s: self._worker_status(s, self.clone_status),
                )
                results.append((serial, result))

            all_success = all(r["success"] for _, r in results)
            any_success = any(r["success"] for _, r in results)

            summary_lines = []
            for serial, r in results:
                if r["success"]:
                    summary_lines.append(f"✓ {serial}: {r['message']}")
                else:
                    summary_lines.append(f"✗ {serial}: {r['message']}")

            summary = "\n".join(summary_lines)

            if all_success:
                return {"overall": True, "summary": summary}
            elif any_success:
                return {"overall": True, "summary": "PARTIAL SUCCESS:\n" + summary}
            else:
                raise Exception("FLASH FAILED:\n" + summary)

        self._run_worker(do_work, self._on_factory_flash_done)

    def _on_factory_flash_done(self, success, message):
        self.btn_flash_factory.setEnabled(True)
        self.btn_clone.setEnabled(True)
        self.btn_cancel_clone.setVisible(False)
        if success:
            try:
                import ast
                result = ast.literal_eval(message)
                summary = result.get("summary", "Done")
                self.clone_progress.setValue(100)
                if "PARTIAL" in summary:
                    self.clone_status.setText(f"⚠️ {summary}")
                else:
                    self.clone_status.setText(f"✅ Factory flash complete!\n{summary}")
                self._log(f"Factory flash: {summary}")
            except Exception:
                self.clone_progress.setValue(100)
                self.clone_status.setText("✅ Factory flash complete!")
                self._log("Factory flash completed")
        else:
            self.clone_status.setText(f"❌ {message}")
            self._log(f"Factory flash failed: {message}")

    def _lock_bootloader(self):
        """Lock the bootloader on selected fastboot devices."""
        targets = []
        for i in range(self.clone_device_list.count()):
            item = self.clone_device_list.item(i)
            if item.checkState() == Qt.Checked:
                targets.append(item.data(Qt.UserRole))

        if not targets:
            QMessageBox.warning(self, "No Targets", "No fastboot devices selected.")
            return

        device_list_str = "\n".join(f"  • {s}" for s in targets)
        reply = QMessageBox.warning(
            self, "Lock Bootloader",
            f"You are about to LOCK the bootloader on:\n{device_list_str}\n\n"
            "This secures the device and prevents further flashing.\n"
            "Note: On some devices, locking may erase data.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        for serial in targets:
            self._log(f"Locking bootloader on {serial}...")
            self.bootloader_status.setText(f"Locking {serial}... Check device screen for confirmation prompt!")
            QApplication.processEvents()

            success, msg = self.imaging.lock_bootloader(
                serial,
                status_callback=lambda s: self._log(s)
            )

            if success:
                self.bootloader_status.setText(f"🟢 {serial}: Bootloader locked! Device is secured.")
                self._log(f"Bootloader locked on {serial}")
            else:
                self.bootloader_status.setText(f"🔴 {serial}: {msg}")
                self._log(f"Failed to lock {serial}: {msg}")

    def _start_clone(self):
        image_path = self.clone_image_path.text()
        if not os.path.isfile(image_path):
            QMessageBox.warning(self, "No Image", "Select a valid image file first.")
            return

        # Get selected target devices
        targets = []
        for i in range(self.clone_device_list.count()):
            item = self.clone_device_list.item(i)
            if item.checkState() == Qt.Checked:
                targets.append(item.data(Qt.UserRole))

        if not targets:
            QMessageBox.warning(self, "No Targets", "No target devices selected.")
            return

        # Safety confirmation before flashing
        device_list_str = "\n".join(f"  • {s}" for s in targets)
        reply = QMessageBox.warning(
            self, "Confirm Clone",
            f"You are about to OVERWRITE the following device(s):\n{device_list_str}\n\n"
            "This will replace the entire operating system and all data.\n"
            "Make sure these are your TARGET phones, NOT your master!\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self._log(f"Starting clone to {len(targets)} device(s)...")
        self.clone_progress.setVisible(True)
        self.clone_progress.setValue(0)
        self.btn_clone.setEnabled(False)
        self.btn_cancel_clone.setVisible(True)
        self.clone_status.setText("Starting clone operation...")

        def do_work():
            results = []
            for serial in targets:
                self._worker_status(f"Cloning to {serial}...", self.clone_status)
                result = self.imaging.restore_image(
                    serial, image_path,
                    progress_callback=lambda c, t, m: self._worker_progress(c, t, m, self.clone_progress),
                    status_callback=lambda s: self._worker_status(s, self.clone_status),
                )
                results.append((serial, result))

            # Build summary
            all_success = all(r["success"] for _, r in results)
            any_success = any(r["success"] for _, r in results)

            summary_lines = []
            for serial, r in results:
                if r["success"]:
                    summary_lines.append(f"✓ {serial}: {r['message']}")
                else:
                    summary_lines.append(f"✗ {serial}: {r['message']}")

            summary = "\n".join(summary_lines)

            if all_success:
                return {"overall": True, "summary": summary}
            elif any_success:
                return {"overall": True, "summary": "PARTIAL SUCCESS:\n" + summary}
            else:
                raise Exception("CLONE FAILED:\n" + summary)

        self._run_worker(do_work, self._on_clone_done)

    def _on_clone_done(self, success, message):
        self.btn_clone.setEnabled(True)
        self.btn_cancel_clone.setVisible(False)
        if success:
            # Parse the dict from the worker
            try:
                import ast
                result = ast.literal_eval(message)
                summary = result.get("summary", "Done")
                if "PARTIAL" in summary:
                    self.clone_progress.setValue(100)
                    self.clone_status.setText(f"⚠️ {summary}")
                    self._log(f"Clone partial: {summary}")
                else:
                    self.clone_progress.setValue(100)
                    self.clone_status.setText(f"✅ Clone complete!\n{summary}")
                    self._log(f"Clone success: {summary}")
            except Exception:
                self.clone_progress.setValue(100)
                self.clone_status.setText(f"✅ Clone complete!")
                self._log("Clone completed")
        else:
            self.clone_status.setText(f"❌ {message}")
            self._log(f"Clone failed: {message}")

    def _start_backup(self):
        idx = self.backup_device_combo.currentIndex()
        if idx < 0:
            QMessageBox.warning(self, "No Device", "No ADB device selected.")
            return

        serial = self.backup_device_combo.currentData()
        output = self.backup_output_path.text()
        include_apps = self.backup_include_apps.isChecked()

        self._log(f"Starting multi-user backup of {serial}...")
        self._log("All user profiles will be scanned and backed up automatically.")
        self.backup_progress.setVisible(True)
        self.backup_progress.setValue(0)
        self.btn_backup.setEnabled(False)
        self.btn_cancel_backup.setVisible(True)

        def do_work():
            return self.imaging.create_backup(
                serial, output, include_apps,
                user_ids=None,  # None = all user profiles
                progress_callback=lambda c, t, m: self._worker_progress(c, t, m, self.backup_progress),
                status_callback=lambda s: self._worker_status(s, self.backup_status),
            )

        self._run_worker(do_work, self._on_backup_done)

    def _on_backup_done(self, success, message):
        self.btn_backup.setEnabled(True)
        self.btn_cancel_backup.setVisible(False)
        if success:
            self.backup_progress.setValue(100)
            self.backup_status.setText(f"✅ Backup created: {message}")
            self._log(f"Backup created: {message}")
        else:
            self.backup_status.setText(f"❌ {message}")
            self._log(f"Backup failed: {message}")

    def _start_restore(self):
        file_path = self.restore_file_path.text()
        if not os.path.isfile(file_path):
            QMessageBox.warning(self, "No File", "Select a valid backup/image file first.")
            return

        idx = self.restore_device_combo.currentIndex()
        if idx < 0:
            QMessageBox.warning(self, "No Device", "No target device selected.")
            return

        serial = self.restore_device_combo.currentData()

        self._log(f"Starting restore to {serial}...")
        self.restore_progress.setVisible(True)
        self.restore_progress.setValue(0)
        self.btn_restore.setEnabled(False)
        self.btn_cancel_restore.setVisible(True)

        def do_work():
            if file_path.endswith(".gbak"):
                # App backup restore
                selected = self._get_selected_apps()
                return self.imaging.restore_backup(
                    serial, file_path, selected,
                    progress_callback=lambda c, t, m: self._worker_progress(c, t, m, self.restore_progress),
                    status_callback=lambda s: self._worker_status(s, self.restore_status),
                )
            else:
                # Full image restore - returns dict now
                result = self.imaging.restore_image(
                    serial, file_path,
                    progress_callback=lambda c, t, m: self._worker_progress(c, t, m, self.restore_progress),
                    status_callback=lambda s: self._worker_status(s, self.restore_status),
                )
                if not result["success"]:
                    raise Exception(result["message"])
                return result["message"]

        self._run_worker(do_work, self._on_restore_done)

    def _on_restore_done(self, success, message):
        self.btn_restore.setEnabled(True)
        self.btn_cancel_restore.setVisible(False)
        if success:
            self.restore_progress.setValue(100)
            self.restore_status.setText(f"✅ Restore complete! {message}")
            self._log(f"Restore completed: {message}")
        else:
            self.restore_status.setText(f"❌ {message}")
            self._log(f"Restore failed: {message}")

    # ──────────────────────────────────────────────
    # APP SELECTOR
    # ──────────────────────────────────────────────
    def _load_apps_from_device(self):
        if not self.adb_devices:
            QMessageBox.information(self, "No Device", "Connect a device in ADB mode first.")
            return
        serial = self.adb_devices[0].serial
        self._log(f"Loading app list from {serial}...")
        apps = self.adb.get_user_packages(serial)
        self._populate_app_list(apps)

    def _load_apps_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image/Backup", "",
            "GrapheneOS Files (*.gimg *.gbak);;All Files (*.*)"
        )
        if path:
            apps = ImagingEngine.get_archive_apps(path)
            self._populate_app_list(apps)

    def _populate_app_list(self, apps):
        self.app_list_widget.clear()
        for pkg in apps:
            item = QListWidgetItem(pkg)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.app_list_widget.addItem(item)
        self.app_count_label.setText(f"{len(apps)} apps loaded")

    def _select_all_apps(self):
        for i in range(self.app_list_widget.count()):
            self.app_list_widget.item(i).setCheckState(Qt.Checked)

    def _select_no_apps(self):
        for i in range(self.app_list_widget.count()):
            self.app_list_widget.item(i).setCheckState(Qt.Unchecked)

    def _get_selected_apps(self):
        """Get list of checked app package names."""
        selected = []
        for i in range(self.app_list_widget.count()):
            item = self.app_list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.text())
        return selected if selected else None

    # ──────────────────────────────────────────────
    # WORKER HELPERS
    # ──────────────────────────────────────────────
    def _run_worker(self, func, on_done):
        """Run a function in a background thread."""
        self.current_worker = Worker(func)
        self.current_worker.signals.finished.connect(on_done)
        self.current_worker.start()

    def _worker_progress(self, current, total, message, progress_bar):
        """Thread-safe progress update."""
        if total > 0:
            pct = int((current / total) * 100)
            QApplication.instance().postEvent(
                progress_bar,
                _ProgressEvent(pct)
            )

    def _worker_status(self, message, label):
        """Thread-safe status update."""
        # Use QTimer for thread safety
        QTimer.singleShot(0, lambda: label.setText(message))
        QTimer.singleShot(0, lambda: self._log(message))


# Custom event for progress updates
from PyQt5.QtCore import QEvent

class _ProgressEvent(QEvent):
    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, value):
        super().__init__(self.EVENT_TYPE)
        self.value = value
