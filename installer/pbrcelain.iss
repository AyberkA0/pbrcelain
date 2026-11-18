; Windows installer for PBRCELAIN (Inno Setup 6).
;
; build_release.py compiles it after PyInstaller has built dist\PBRCELAIN:
;   ISCC.exe /DAppVersion=<version> /DSourceDir=<dist\PBRCELAIN> /DOutputDir=<release> installer\pbrcelain.iss
;
; By default it installs for the current user only, without asking for admin
; rights (into %LOCALAPPDATA%\Programs\PBRCELAIN); the first page offers an
; install for all users instead.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\PBRCELAIN"
#endif
#ifndef OutputDir
  #define OutputDir "..\release"
#endif

#define AppName "PBRCELAIN"
#define AppExe "PBRCELAIN.exe"
#define ProgId "PBRCELAIN.Project"

[Setup]
; Never change AppId: Windows uses it to find an installed PBRCELAIN to update.
AppId={{6C1D5F0B-8E2A-4B7C-9A4E-3F2D1C0B9A87}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
AppPublisherURL=https://github.com/AyberkA0/pbrcelain
AppSupportURL=https://github.com/AyberkA0/pbrcelain/issues
AppUpdatesURL=https://github.com/AyberkA0/pbrcelain/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE
SetupIconFile=..\ui\assets\app_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir={#OutputDir}
OutputBaseFilename={#AppName}-{#AppVersion}-Windows-x64-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Files of an older version that the new one no longer has.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; The AppUserModelID matches the one main.py sets, so the taskbar groups the
; running app with its pinned shortcut.
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "PBRCELAIN.App"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "PBRCELAIN.App"; Tasks: desktopicon

[Registry]
; Open .pcln projects with PBRCELAIN.
Root: HKA; Subkey: "Software\Classes\.pcln"; ValueType: string; ValueName: ""; ValueData: "{#ProgId}"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\.pcln\OpenWithProgids"; ValueType: string; ValueName: "{#ProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueName: ""; ValueData: "PBRCELAIN Project"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#ProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",0"
Root: HKA; Subkey: "Software\Classes\{#ProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The AI components the app downloaded (up to about 2 GB). The depth models
; stay: they are in the Hugging Face cache, which other programs share.
Type: filesandordirs; Name: "{localappdata}\PBRCELAIN"

[Code]
// The app's settings (window layout, recent projects, "don't show again").
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteKeyIncludingSubkeys(HKEY_CURRENT_USER, 'Software\PBRCELAIN');
end;
