; Inno Setup script for UGC-Trend-Finder-Setup.exe. Paths are relative to this folder.
#define AppName "UGC Trend Finder"
#define AppExe "UGC Trend Finder.exe"
#ifndef AppVersion
  #define AppVersion "1.2"
#endif

[Setup]
AppId={{8C5E2A1B-4F3D-4E7A-9B61-2D7C9E0F4A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
DefaultDirName={localappdata}\Programs\{#AppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableWelcomePage=yes
PrivilegesRequired=lowest
OutputDir=..\Output
OutputBaseFilename=UGC-Trend-Finder-Setup
SetupIconFile=..\src\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=100
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Put a shortcut on my desktop"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start with Windows (runs quietly in the tray)"; GroupDescription: "Shortcuts:"; Flags: unchecked

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\src\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: "--tray"; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName} now"; Flags: nowait postinstall

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM ""{#AppExe}"" /F"; Flags: runhidden; RunOnceId: "KillApp"
