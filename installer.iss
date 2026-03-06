; Inno Setup Script for GrapheneOS Cloner
; Produces a signed Windows installer

[Setup]
AppName=GrapheneOS Cloner
AppVersion=1.0.0
AppPublisher=GrapheneOS Cloner
DefaultDirName={autopf}\GrapheneOS Cloner
DefaultGroupName=GrapheneOS Cloner
OutputBaseFilename=GrapheneOS_Cloner_Setup_v1.0.0
OutputDir=installer_output
Compression=lzma2
SolidCompression=yes
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\GrapheneOS_Cloner.exe
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main application files (from PyInstaller output)
Source: "dist\GrapheneOS_Cloner\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Google USB Drivers
Source: "drivers\*"; DestDir: "{app}\drivers"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\GrapheneOS Cloner"; Filename: "{app}\GrapheneOS_Cloner.exe"
Name: "{group}\Uninstall GrapheneOS Cloner"; Filename: "{uninstallexe}"
Name: "{autodesktop}\GrapheneOS Cloner"; Filename: "{app}\GrapheneOS_Cloner.exe"; Tasks: desktopicon

[Run]
; Install Google USB drivers silently
Filename: "{app}\drivers\install_drivers.bat"; Parameters: ""; StatusMsg: "Installing USB drivers..."; Flags: runhidden waituntilterminated; Check: ShouldInstallDrivers

; Launch app after install
Filename: "{app}\GrapheneOS_Cloner.exe"; Description: "Launch GrapheneOS Cloner"; Flags: nowait postinstall skipifsilent

[Code]
function ShouldInstallDrivers: Boolean;
begin
  Result := MsgBox('Would you like to install Google USB Drivers?' + #13#10 +
    '(Required if not already installed)', mbConfirmation, MB_YESNO) = IDYES;
end;
