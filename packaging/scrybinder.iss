; Inno Setup script. Run from the repository root after PyInstaller:  iscc /DAppVersion=0.1.0 packaging\scrybinder.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
[Setup]
AppId={{6F0B7A52-3C1E-4C0B-9D5B-5C2B7B1A9E01}
AppName=Scrybinder
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Scrybinder
DefaultGroupName=Scrybinder
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Scrybinder-{#AppVersion}-windows-setup
SetupIconFile=..\assets\scrybinder.ico
UninstallDisplayIcon={app}\Scrybinder.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
[Files]
Source: "..\dist\Scrybinder\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
[Icons]
Name: "{group}\Scrybinder"; Filename: "{app}\Scrybinder.exe"
Name: "{autodesktop}\Scrybinder"; Filename: "{app}\Scrybinder.exe"; Tasks: desktopicon
[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"
[Run]
Filename: "{app}\Scrybinder.exe"; Description: "Launch Scrybinder"; Flags: nowait postinstall skipifsilent
