; Build only through build_installer.py, which supplies verified staging paths.
#ifndef VoiceAvailable
  #define VoiceAvailable 1
#endif
[Setup]
AppId={{21CDD0EF-61B0-4A4F-B35E-816026C65F23}
AppName=Расписание
AppVersion={#AppVersion}
AppPublisher=Школьное расписание
DefaultDirName={localappdata}\Programs\SchoolSchedule
DefaultGroupName=Расписание
DisableProgramGroupPage=yes
DisableDirPage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir={#OutputPath}
#if Int(VoiceAvailable)
OutputBaseFilename=Расписание-установка-{#AppVersion}
#else
OutputBaseFilename=Расписание-установка-{#AppVersion}-без-голоса
#endif
SetupIconFile={#StagePath}\_internal\app\static\favicon.ico
UninstallDisplayIcon={app}\_internal\app\static\favicon.ico
Uninstallable=not IsQa
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
DisableWelcomePage=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Types]
Name: "compact"; Description: "Без голосового ввода"
#if Int(VoiceAvailable)
Name: "full"; Description: "С голосовым вводом"
#endif
Name: "custom"; Description: "Выбор компонентов"; Flags: iscustom

[Components]
#if Int(VoiceAvailable)
Name: "main"; Description: "Расписание, AI-помощник и отчёты"; Types: compact full custom; Flags: fixed
#else
Name: "main"; Description: "Расписание, AI-помощник и отчёты"; Types: compact custom; Flags: fixed
#endif
#if Int(VoiceAvailable)
Name: "voice"; Description: "Голосовой ввод (дополнительно около 2 ГБ на диске)"; Types: full
#endif

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Check: not IsQa

[Files]
Source: "{#StagePath}\*"; DestDir: "{app}"; Excludes: "_internal\assets\speech-whisper\*"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "{#DefaultsPath}"; DestDir: "{code:DataDir}"; DestName: "assistant-connection.json"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "{#WebViewSetup}"; Flags: dontcopy
#if Int(VoiceAvailable)
Source: "{#StagePath}\_internal\assets\speech-whisper\*"; DestDir: "{app}\_internal\assets\speech-whisper"; Flags: ignoreversion recursesubdirs createallsubdirs solidbreak; Components: voice
#endif

[Icons]
Name: "{group}\Расписание"; Filename: "{app}\Расписание.exe"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\app\static\favicon.ico"; AppUserModelID: "School.Raspisanie.2026"; Check: not IsQa
Name: "{userdesktop}\Расписание"; Filename: "{app}\Расписание.exe"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\app\static\favicon.ico"; AppUserModelID: "School.Raspisanie.2026"; Tasks: desktopicon; Check: not IsQa

[Run]
Filename: "{app}\Расписание.exe"; Description: "Открыть расписание"; Flags: nowait postinstall skipifsilent; Check: not IsQa

[Code]
function IsQa: Boolean;
begin
  Result := ExpandConstant('{param:QA|0}') = '1';
end;

function DataDir(Param: String): String;
begin
  if IsQa then Result := ExpandConstant('{app}\data-qa')
  else Result := ExpandConstant('{localappdata}\SchoolSchedule\Data');
end;

function HasWebView: Boolean;
var ExitCode: Integer;
begin
  Result := Exec(ExpandConstant('{app}\Расписание.exe'), '--check-webview',
    ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ExitCode) and (ExitCode = 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var ExitCode: Integer; ExistingComponents: AnsiString; KeepVoice: Boolean; LegacySeed, PrivateSeed: String;
begin
  if CurStep = ssInstall then begin
    LegacySeed := ExpandConstant('{app}\_internal\app\seed.json');
    PrivateSeed := DataDir('') + '\factory-seed.json';
    if FileExists(LegacySeed) then begin
      ForceDirectories(DataDir(''));
      if FileExists(PrivateSeed) then
        if not FileCopy(PrivateSeed, DataDir('') + '\factory-seed.previous.json', False) then
          RaiseException('Не удалось сохранить прежние настройки школы. Закройте приложение и повторите установку.');
      if not FileCopy(LegacySeed, PrivateSeed, False) then
        RaiseException('Не удалось перенести настройки школы. Данные сохранены в прежней папке.');
      if GetSHA256OfFile(LegacySeed) <> GetSHA256OfFile(PrivateSeed) then
        RaiseException('Копия настроек школы не прошла проверку. Обновление остановлено.');
      DeleteFile(LegacySeed);
    end;
    { Preserve private legacy Word templates before any program files change. }
    ForceDirectories(DataDir('') + '\templates');
    if not FileExists(DataDir('') + '\templates\ПОНЕДЕЛЬНИК УЧИТЕЛЬ.docx') then
      FileCopy(ExpandConstant('{app}\_internal\app\templates\ПОНЕДЕЛЬНИК УЧИТЕЛЬ.docx'), DataDir('') + '\templates\ПОНЕДЕЛЬНИК УЧИТЕЛЬ.docx', True);
    if not FileExists(DataDir('') + '\templates\ПОНЕДЕЛЬНИК УЧЕНИК.docx') then
      FileCopy(ExpandConstant('{app}\_internal\app\templates\ПОНЕДЕЛЬНИК УЧЕНИК.docx'), DataDir('') + '\templates\ПОНЕДЕЛЬНИК УЧЕНИК.docx', True);
    if not FileExists(DataDir('') + '\templates\ВТОРНИК УЧИТЕЛЬ.docx') then
      FileCopy(ExpandConstant('{app}\_internal\app\templates\ВТОРНИК УЧИТЕЛЬ.docx'), DataDir('') + '\templates\ВТОРНИК УЧИТЕЛЬ.docx', True);
    if not FileExists(DataDir('') + '\templates\ВТОРНИК УЧЕНИК.docx') then
      FileCopy(ExpandConstant('{app}\_internal\app\templates\ВТОРНИК УЧЕНИК.docx'), DataDir('') + '\templates\ВТОРНИК УЧЕНИК.docx', True);
  end;
  if CurStep = ssPostInstall then begin
    KeepVoice := False;
    if (ExpandConstant('{param:UPDATE|0}') = '1') or ({#VoiceAvailable} = 0) then begin
      if LoadStringFromFile(ExpandConstant('{app}\installed-components.json'), ExistingComponents) then
        KeepVoice := (Pos('true', String(ExistingComponents)) > 0) and FileExists(ExpandConstant('{app}\_internal\assets\speech-whisper\model.bin'));
    end;
#if Int(VoiceAvailable)
    if WizardIsComponentSelected('voice') or KeepVoice then
      SaveStringToFile(ExpandConstant('{app}\installed-components.json'), '{"voice":true}', False)
    else
#endif
      if KeepVoice then
        SaveStringToFile(ExpandConstant('{app}\installed-components.json'), '{"voice":true}', False)
      else
        SaveStringToFile(ExpandConstant('{app}\installed-components.json'), '{"voice":false}', False);
  end;
  if (CurStep = ssPostInstall) and not HasWebView then begin
    WizardForm.StatusLabel.Caption := 'Подготавливаем окно приложения… Требуется подключение к интернету.';
    ExtractTemporaryFile('MicrosoftEdgeWebView2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebView2Setup.exe'), '/silent /install',
      '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      RaiseException('Не удалось подготовить окно приложения. Подключите интернет и повторите установку.');
    if not HasWebView then
      RaiseException('Компонент окна приложения ещё не готов. Перезагрузите компьютер и повторите установку с подключённым интернетом.');
  end;
end;
