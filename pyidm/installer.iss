; installer.iss - Inno Setup 6 Script for CIDM Windows Installer
; Builds a clean installer (CIDM_Setup.exe) from dist\CIDM

#define MyAppName "CIDM"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "CIDM Team"
#define MyAppURL "https://github.com/cidm"
#define MyAppExeName "CIDM.exe"

[Setup]
; Unique application identifier (generated for CIDM)
AppId={{9B7E34B5-7F16-43C6-9BC5-9A91D6EB0842}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Installation target directory and Start Menu group
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; Visuals & Branding
SetupIconFile=assets\cidm.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern

; Compression and output directory
OutputDir=Output
OutputBaseFilename=CIDM_Setup
Compression=lzma2/max
SolidCompression=yes

; Process and upgrade handling: cleanly terminate running instance on upgrade/uninstall
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName}
RestartApplications=no
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startupicon"; Description: "Run {#MyAppName} in the background on Windows startup"; GroupDescription: "Additional options:"; Flags: checkablealone
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "Additional options:"; Flags: unchecked

[Files]
Source: "dist\CIDM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "chrome_extension\*"; DestDir: "{app}\extension\chromium"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "chrome_extension\*"; DestDir: "{app}\extension"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "chrome_extension\*"; DestDir: "{app}\chrome_extension"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "firefox_extension\*"; DestDir: "{app}\extension\firefox"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "firefox_extension\*"; DestDir: "{app}\firefox_extension"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Register automatic launch on Windows Startup when 'startupicon' task is selected
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"" --minimized"; Flags: uninsdeletevalue; Tasks: startupicon

[Run]
; Post-install launch checkbox
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Terminate background process before removing files during uninstallation
Filename: "taskkill.exe"; Parameters: "/F /IM {#MyAppExeName} /T"; Flags: runhidden; RunOnceId: "KillCIDMBeforeUninstall"

[InstallDelete]
; If an older or failed installation created 'assets' as a file, remove it so the assets directory can be created
Type: files; Name: "{app}\assets"
; Clean up any leftover temporary fragment files
Type: files; Name: "{app}\*.cidm_part"
Type: files; Name: "{app}\*.pyidm_part"
