"""
GrapheneOS Cloner - Configuration
"""
import os
import sys

APP_NAME = "GrapheneOS Cloner"
APP_VERSION = "1.6.6"
APP_AUTHOR = "GrapheneOS Cloner"

# Bundled / downloadable factory images
# Pixel 3 (blueline) — last GrapheneOS build (Feb 2023, discontinued)
FACTORY_IMAGE_URLS = {
    "blueline": {
        "name": "Pixel 3 (blueline) — GrapheneOS 2023020600",
        "url": "https://web.archive.org/web/20230418211733/https://releases.grapheneos.org/blueline-factory-2023020600.zip",
        "sig_url": "https://web.archive.org/web/20230418203501/https://releases.grapheneos.org/blueline-factory-2023020600.zip.sig",
        "filename": "blueline-factory-2023020600.zip",
        "sig_filename": "blueline-factory-2023020600.zip.sig",
    },
}

# Supported Pixel devices and their partition layouts
# GrapheneOS supports: Pixel 3/3a/4/4a/5/5a/6/6a/6 Pro/7/7a/7 Pro/8/8a/8 Pro/9/9 Pro
DEVICE_PARTITIONS = {
    # Pixel 3 / 3 XL (blueline / crosshatch)
    "blueline": ["boot", "dtbo", "system", "vendor", "product", "userdata", "vbmeta", "vbmeta_system"],
    "crosshatch": ["boot", "dtbo", "system", "vendor", "product", "userdata", "vbmeta", "vbmeta_system"],
    # Pixel 3a / 3a XL (sargo / bonito)
    "sargo": ["boot", "dtbo", "system", "vendor", "product", "userdata", "vbmeta", "vbmeta_system"],
    "bonito": ["boot", "dtbo", "system", "vendor", "product", "userdata", "vbmeta", "vbmeta_system"],
    # Pixel 4 / 4 XL (flame / coral)
    "flame": ["boot", "dtbo", "system", "vendor", "product", "userdata", "vbmeta", "vbmeta_system"],
    "coral": ["boot", "dtbo", "system", "vendor", "product", "userdata", "vbmeta", "vbmeta_system"],
    # Pixel 4a (sunfish)
    "sunfish": ["boot", "dtbo", "system", "vendor", "product", "userdata", "vbmeta", "vbmeta_system"],
    # Pixel 4a 5G / 5 (bramble / redfin)
    "bramble": ["boot", "dtbo", "system", "vendor", "product", "userdata", "vbmeta", "vbmeta_system"],
    "redfin": ["boot", "dtbo", "system", "vendor", "product", "userdata", "vbmeta", "vbmeta_system"],
    # Pixel 5a (barbet)
    "barbet": ["boot", "dtbo", "system", "vendor", "product", "userdata", "vbmeta", "vbmeta_system"],
    # Pixel 6 / 6 Pro / 6a (oriole / raven / bluejay) - tensor, has init_boot
    "oriole": ["boot", "init_boot", "dtbo", "system", "vendor", "product", "system_ext", "userdata", "vbmeta", "vbmeta_system"],
    "raven": ["boot", "init_boot", "dtbo", "system", "vendor", "product", "system_ext", "userdata", "vbmeta", "vbmeta_system"],
    "bluejay": ["boot", "init_boot", "dtbo", "system", "vendor", "product", "system_ext", "userdata", "vbmeta", "vbmeta_system"],
    # Pixel 7 / 7 Pro / 7a (panther / cheetah / lynx)
    "panther": ["boot", "init_boot", "dtbo", "system", "vendor", "product", "system_ext", "userdata", "vbmeta", "vbmeta_system"],
    "cheetah": ["boot", "init_boot", "dtbo", "system", "vendor", "product", "system_ext", "userdata", "vbmeta", "vbmeta_system"],
    "lynx": ["boot", "init_boot", "dtbo", "system", "vendor", "product", "system_ext", "userdata", "vbmeta", "vbmeta_system"],
    # Pixel 8 / 8 Pro / 8a (shiba / husky / akita)
    "shiba": ["boot", "init_boot", "dtbo", "system", "vendor", "product", "system_ext", "userdata", "vbmeta", "vbmeta_system"],
    "husky": ["boot", "init_boot", "dtbo", "system", "vendor", "product", "system_ext", "userdata", "vbmeta", "vbmeta_system"],
    "akita": ["boot", "init_boot", "dtbo", "system", "vendor", "product", "system_ext", "userdata", "vbmeta", "vbmeta_system"],
    # Pixel 9 / 9 Pro / 9 Pro XL / 9 Pro Fold (tokay / caiman / komodo / comet)
    "tokay": ["boot", "init_boot", "dtbo", "system", "vendor", "product", "system_ext", "userdata", "vbmeta", "vbmeta_system"],
    "caiman": ["boot", "init_boot", "dtbo", "system", "vendor", "product", "system_ext", "userdata", "vbmeta", "vbmeta_system"],
    "komodo": ["boot", "init_boot", "dtbo", "system", "vendor", "product", "system_ext", "userdata", "vbmeta", "vbmeta_system"],
    "comet": ["boot", "init_boot", "dtbo", "system", "vendor", "product", "system_ext", "userdata", "vbmeta", "vbmeta_system"],
}

# Friendly names for device codenames
DEVICE_NAMES = {
    "blueline": "Pixel 3", "crosshatch": "Pixel 3 XL",
    "sargo": "Pixel 3a", "bonito": "Pixel 3a XL",
    "flame": "Pixel 4", "coral": "Pixel 4 XL",
    "sunfish": "Pixel 4a",
    "bramble": "Pixel 4a 5G", "redfin": "Pixel 5",
    "barbet": "Pixel 5a",
    "oriole": "Pixel 6", "raven": "Pixel 6 Pro", "bluejay": "Pixel 6a",
    "panther": "Pixel 7", "cheetah": "Pixel 7 Pro", "lynx": "Pixel 7a",
    "shiba": "Pixel 8", "husky": "Pixel 8 Pro", "akita": "Pixel 8a",
    "tokay": "Pixel 9", "caiman": "Pixel 9 Pro", "komodo": "Pixel 9 Pro XL", "comet": "Pixel 9 Pro Fold",
}

# Fallback partition list (for unknown devices)
DEFAULT_PARTITIONS = ["boot", "dtbo", "system", "vendor", "product", "userdata", "vbmeta", "vbmeta_system"]

# Legacy alias
PIXEL3_PARTITIONS = DEVICE_PARTITIONS["blueline"]


def get_partitions_for_device(codename: str) -> list:
    """Get the partition list for a specific device codename."""
    return DEVICE_PARTITIONS.get(codename.lower(), DEFAULT_PARTITIONS)


def get_device_friendly_name(codename: str) -> str:
    """Get the friendly name for a device codename."""
    return DEVICE_NAMES.get(codename.lower(), codename)


# Partitions that contain the OS (flashed via fastboot) - derived per device
def get_system_partitions(codename: str) -> list:
    """Get OS partitions (everything except userdata) for a device."""
    parts = get_partitions_for_device(codename)
    return [p for p in parts if p != "userdata"]


SYSTEM_PARTITIONS = ["boot", "dtbo", "system", "vendor", "product", "vbmeta", "vbmeta_system"]

# Partition containing user data and apps
DATA_PARTITION = "userdata"

# Image file extension
IMAGE_EXTENSION = ".img"
ARCHIVE_EXTENSION = ".gimg"
BACKUP_EXTENSION = ".gbak"

# ADB/Fastboot binary names
if sys.platform == "win32":
    ADB_BINARY = "adb.exe"
    FASTBOOT_BINARY = "fastboot.exe"
else:
    ADB_BINARY = "adb"
    FASTBOOT_BINARY = "fastboot"


def get_tools_dir():
    """Get the directory containing adb/fastboot binaries."""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "tools")


def get_adb_path():
    return os.path.join(get_tools_dir(), ADB_BINARY)


def get_fastboot_path():
    return os.path.join(get_tools_dir(), FASTBOOT_BINARY)


# Default image storage directory
def get_default_image_dir():
    return os.path.join(os.path.expanduser("~"), "GrapheneOS_Cloner", "images")


def get_default_backup_dir():
    return os.path.join(os.path.expanduser("~"), "GrapheneOS_Cloner", "backups")


def get_factory_images_dir():
    """Directory where downloaded factory images are stored."""
    return os.path.join(os.path.expanduser("~"), "GrapheneOS_Cloner", "factory_images")
