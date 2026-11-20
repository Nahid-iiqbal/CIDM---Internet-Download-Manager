; installer.iss - Inno Setup 6 Script for CIDM Windows Installer
; Builds a clean installer (CIDM_Setup.exe) from dist\CIDM

#define MyAppName "CIDM"
#define MyAppVersion "1.0.2"
#define MyAppPublisher "CIDM Team"
#define MyAppURL "https://github.com/cidm"
#define MyAppExeName "CIDM.exe"
#define MyAppId "{9B7E34B5-7F16-43C6-9BC5-9A91D6EB0842}"

[Setup]
; Unique application identifier (generated for CIDM)
AppId={{9B7E34B5-7F16-43C6-9BC5-9A91D6EB0842}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Installation target directory and Start Menu group (auto-detects existing installation folder)
DefaultDirName={code:GetInstallDir|{autopf}\{#MyAppName}}
UsePreviousAppDir=yes
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

[Code]
// Retrieve uninstall string for existing installation (checks HKCU then HKLM)
function GetUninstallString(): String;
var
  sUnInstPath: String;
  sUnInstallString: String;
begin
  sUnInstPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1';
  sUnInstallString := '';
  if not RegQueryStringValue(HKCU, sUnInstPath, 'UninstallString', sUnInstallString) then
    RegQueryStringValue(HKLM, sUnInstPath, 'UninstallString', sUnInstallString);
  Result := sUnInstallString;
end;

// Retrieve existing installation directory (checks HKCU then HKLM)
function GetExistingAppDir(): String;
var
  sUnInstPath: String;
  sAppDir: String;
  sUnInstallString: String;
begin
  sUnInstPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1';
  sAppDir := '';
  if not RegQueryStringValue(HKCU, sUnInstPath, 'Inno Setup: App Path', sAppDir) then
    if not RegQueryStringValue(HKLM, sUnInstPath, 'Inno Setup: App Path', sAppDir) then
      if not RegQueryStringValue(HKCU, sUnInstPath, 'InstallLocation', sAppDir) then
        RegQueryStringValue(HKLM, sUnInstPath, 'InstallLocation', sAppDir);

  // Fallback: extract directory from UninstallString if present
  if sAppDir = '' then
  begin
    sUnInstallString := GetUninstallString();
    if sUnInstallString <> '' then
      sAppDir := ExtractFileDir(RemoveQuotes(sUnInstallString));
  end;

  Result := sAppDir;
end;

// Custom directory provider for DefaultDirName: pre-selects existing directory
function GetInstallDir(DefaultParam: String): String;
var
  sExisting: String;
begin
  sExisting := GetExistingAppDir();
  if (sExisting <> '') and DirExists(sExisting) then
    Result := sExisting
  else
    Result := DefaultParam;
end;

// Check if an existing version is installed and has an uninstaller
function IsExistingAppInstalled(): Boolean;
var
  sUnInstallString: String;
begin
  sUnInstallString := GetUninstallString();
  Result := (sUnInstallString <> '') and FileExists(RemoveQuotes(sUnInstallString));
end;

// Cleanly uninstalls the previous installation before extracting new files
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  sUnInstallString: String;
  ResultCode: Integer;
  TargetAssets: String;
begin
  Result := '';

  if IsExistingAppInstalled() then
  begin
    // 1. Terminate running background instances before uninstallation
    Exec('taskkill.exe', '/F /IM CIDM.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('taskkill.exe', '/F /IM pyidm.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    // 2. Silently execute the previous uninstaller to purge old binaries and obsolete files
    sUnInstallString := RemoveQuotes(GetUninstallString());
    if FileExists(sUnInstallString) then
    begin
      Exec(sUnInstallString, '/SILENT /NORESTART /SUPPRESSMSGBOXES', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      Sleep(300);
    end;
  end;

  // 3. Purge any legacy conflict file named 'assets' if an older install created one
  TargetAssets := ExpandConstant('{app}\assets');
  if FileExists(TargetAssets) then
  begin
    DeleteFile(TargetAssets);
  end;
end;
