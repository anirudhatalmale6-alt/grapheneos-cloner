"""
GrapheneOS Cloner - Configuration
"""
import os
import sys

APP_NAME = "GrapheneOS Cloner"
APP_VERSION = "1.0.0"
APP_AUTHOR = "GrapheneOS Cloner"

# Partition list for Pixel 3 (blueline)
# These are the critical partitions needed for a full clone
PIXEL3_PARTITIONS = [
    "boot",
    "dtbo",
    "system",
    "vendor",
    "product",
    "userdata",
    "vbmeta",
    "vbmeta_system",
]

# Partitions that contain the OS (flashed via fastboot)
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
