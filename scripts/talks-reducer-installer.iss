; Talks Reducer Windows installer built with Inno Setup

#define APP_NAME "Talks Reducer"
#ifndef APP_VERSION
  #error "APP_VERSION not set. Pass /DAPP_VERSION=... when invoking ISCC."
#endif
#ifndef APP_PUBLISHER
  #define APP_PUBLISHER "Talks Reducer"
#endif
#ifndef SOURCE_DIR
  #define SOURCE_PRIMARY "..\dist\talks-reducer\"
  #pragma message "Checking installer source: " + SOURCE_PRIMARY

  #ifexist SOURCE_PRIMARY + "talks-reducer.exe"
    #define SOURCE_DIR SOURCE_PRIMARY
  #else
    #define SOURCE_SECOND "..\dist\talks-reducer-windows\"
    #pragma message "Checking installer source: " + SOURCE_SECOND
    #ifexist SOURCE_SECOND + "talks-reducer.exe"
      #define SOURCE_DIR SOURCE_SECOND
    #else
      #define SOURCE_THIRD "..\dist\talks-reducer-windows\talks-reducer\"
      #pragma message "Checking installer source: " + SOURCE_THIRD
      #ifexist SOURCE_THIRD + "talks-reducer.exe"
        #define SOURCE_DIR SOURCE_THIRD
      #endif
    #endif
  #endif
#endif

#ifndef SOURCE_DIR
  #error "Expected PyInstaller bundle under dist. Run scripts/build-gui.sh before packaging."
#endif

#pragma message "Resolved SOURCE_DIR: " + SOURCE_DIR
#ifndef APP_ICON
  #define APP_ICON "..\\talks_reducer\\resources\\icons\\app.ico"
#endif
#ifndef OUTPUT_DIR
  #define OUTPUT_DIR ".."
#endif

#ifnexist SOURCE_DIR + "talks-reducer.exe"
  #error "Expected PyInstaller bundle in {#SOURCE_DIR}. Run scripts/build-gui.sh before packaging."
#endif

[Setup]
AppId={{C5B7F1C7-5AD7-4F40-9D06-6DB5F6FC168A}}
AppName={#APP_NAME}
AppVersion={#APP_VERSION}
AppVerName={#APP_NAME} {#APP_VERSION}
AppPublisher={#APP_PUBLISHER}
DefaultDirName={localappdata}\Programs\talks-reducer
DefaultGroupName=Talks Reducer
DisableProgramGroupPage=no
LicenseFile=..\LICENSE
OutputBaseFilename=talks-reducer-{#APP_VERSION}-setup
OutputDir={#OUTPUT_DIR}
SetupIconFile={#APP_ICON}
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
Compression=lzma
SolidCompression=yes
UninstallDisplayIcon={app}\talks-reducer.exe
; Close running Talks Reducer instances (GUI, tray, dock-server) via the Restart
; Manager so their locked files can be replaced during an update. A taskkill
; fallback in [Code] force-closes anything the Restart Manager cannot.
CloseApplications=yes
CloseApplicationsFilter=talks-reducer.exe
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "addcontext"; Description: "Register ""Open with Talks Reducer"" in Explorer"; GroupDescription: "Shell integration:"; Flags: unchecked
Name: "dockserver_startmenu"; Description: "Add ""OBS Dock Server"" to the Start menu"; GroupDescription: "OBS Processing Dock:"; Flags: unchecked
Name: "dockserver_startup"; Description: "Start the OBS Dock Server automatically at logon"; GroupDescription: "OBS Processing Dock:"; Flags: unchecked

[Files]
Source: "{#SOURCE_DIR}*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Talks Reducer"; Filename: "{app}\talks-reducer.exe"; WorkingDir: "{app}"; IconFilename: "{app}\talks-reducer.exe"
Name: "{group}\Uninstall Talks Reducer"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Talks Reducer"; Filename: "{app}\talks-reducer.exe"; Tasks: desktopicon; WorkingDir: "{app}"; IconFilename: "{app}\talks-reducer.exe"
Name: "{group}\OBS Dock Server"; Filename: "{app}\talks-reducer.exe"; Parameters: "dock-server"; Tasks: dockserver_startmenu; WorkingDir: "{app}"; IconFilename: "{app}\talks-reducer.exe"
Name: "{userstartup}\Talks Reducer OBS Dock Server"; Filename: "{app}\talks-reducer.exe"; Parameters: "dock-server"; Tasks: dockserver_startup; WorkingDir: "{app}"; IconFilename: "{app}\talks-reducer.exe"

[Registry]
Root: HKCU; Subkey: "Software\Classes\*\shell\OpenWithTalksReducer"; ValueType: string; ValueName: ""; ValueData: "Open with Talks Reducer"; Tasks: addcontext; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\*\shell\OpenWithTalksReducer"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\\talks-reducer.exe"",0"; Tasks: addcontext
Root: HKCU; Subkey: "Software\Classes\*\shell\OpenWithTalksReducer\command"; ValueType: string; ValueName: ""; ValueData: """{app}\\talks-reducer.exe"" ""%1"""; Tasks: addcontext; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\OpenWithTalksReducer"; ValueType: string; ValueName: ""; ValueData: "Open with Talks Reducer"; Tasks: addcontext; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Directory\shell\OpenWithTalksReducer"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\\talks-reducer.exe"",0"; Tasks: addcontext
Root: HKCU; Subkey: "Software\Classes\Directory\shell\OpenWithTalksReducer\command"; ValueType: string; ValueName: ""; ValueData: """{app}\\talks-reducer.exe"" ""%1"""; Tasks: addcontext; Flags: uninsdeletekey

[Run]
Filename: "{app}\talks-reducer.exe"; Description: "Launch Talks Reducer"; Flags: nowait postinstall skipifsilent

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  { Fallback for CloseApplications: force-close any Talks Reducer instance the
    Restart Manager could not (e.g. the windowless dock-server) so the files can
    be overwritten during an update. Best-effort: a non-zero exit code (nothing
    running) is ignored. }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM talks-reducer.exe /F /T',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

