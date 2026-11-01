; Установщик RU Local TTS for Twitch (Inno Setup 6). Собирать через setup\build.ps1 — он подставит Src/AppVer/NumVer.
; Ставит только код (~1 МБ) в папку пользователя (без админа, чтобы автообновление могло менять файлы).
; Python, библиотеки и голоса докачивает install.ps1 при первом запуске (TwitchTTS.exe -> start_tts.bat).
; Удаление: спрашивает, оставить ли настройки (config.json и data\), остальное (venv, голоса, модели) — стирает.

#ifndef Src
  #define Src "..\dist\src"
#endif
#ifndef AppVer
  #define AppVer "b0.0"
#endif
#ifndef NumVer
  #define NumVer "0.0.0.0"
#endif

[Setup]
AppId={{8ADF623F-9BC8-4D3B-BF7A-7627D7984E3E}
AppName=Twitch TTS
AppVersion={#AppVer}
AppVerName=Twitch TTS {#AppVer}
VersionInfoVersion={#NumVer}
AppPublisher=Koty9n
AppPublisherURL=https://github.com/Koty9n/RU-Local-TTS-for-Twitch-
AppSupportURL=https://github.com/Koty9n/RU-Local-TTS-for-Twitch-/issues
AppUpdatesURL=https://github.com/Koty9n/RU-Local-TTS-for-Twitch-/releases
DefaultDirName={localappdata}\Programs\TwitchTTS
DisableProgramGroupPage=yes
DirExistsWarning=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=TwitchTTS-Setup-{#AppVer}
SetupIconFile={#Src}\app\assets\icon.ico
UninstallDisplayIcon={app}\TwitchTTS.exe
UninstallDisplayName=Twitch TTS
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Messages]
ru.WelcomeLabel2=Будет установлена озвучка чата Twitch [name/ver].%n%nПри первом запуске программа докачает Python, библиотеки и выбранные голоса (1–2 ГБ, нужен интернет). Дальше она обновляется сама.

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Ярлыки:"

[Files]
; код; config.json и свои списки в data\ при переустановке не перезаписываем
Source: "{#Src}\*"; DestDir: "{app}"; Excludes: "\data\*,\config.json,\docs\*,\.git*"; Flags: recursesubdirs ignoreversion
Source: "{#Src}\data\*"; DestDir: "{app}\data"; Flags: recursesubdirs onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{autoprograms}\Twitch TTS"; Filename: "{app}\TwitchTTS.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\TwitchTTS"; Filename: "{app}\TwitchTTS.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\TwitchTTS.exe"; Description: "Запустить Twitch TTS (первый запуск докачает нужное)"; Flags: postinstall nowait skipifsilent

[Code]
var
  KeepSettings: Boolean;

{ Процессы Python из папки программы. Kill=True — закрыть их. Возвращает True, если что-то было запущено. }
function AppRunning(Dir: String; Kill: Boolean): Boolean;
var
  Cmd, K: String;
  Res: Integer;
begin
  StringChangeEx(Dir, '''', '''''', True);
  if Kill then K := '1' else K := '0';
  Cmd := '-NoProfile -ExecutionPolicy Bypass -Command "$t=''' + RemoveBackslashUnlessRoot(Dir) + '\'';' +
    ' $p=@(Get-Process python*,pythonw* -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($t,[StringComparison]::OrdinalIgnoreCase) });' +
    ' if(-not $p.Count){exit 0}; if(' + K + '){ $p | Stop-Process -Force; Start-Sleep 2 }; exit 1"';
  Result := Exec('powershell.exe', Cmd, '', SW_HIDE, ewWaitUntilTerminated, Res) and (Res = 1);
end;

function AskClose(Dir: String): Boolean;
begin
  Result := True;
  if not AppRunning(Dir, False) then Exit;
  if SuppressibleMsgBox('Twitch TTS сейчас запущен. Закрыть его и продолжить?' + #13#10#13#10 +
     '(Если идёт стрим — лучше «Нет» и продолжить после.)', mbConfirmation, MB_YESNO, IDYES) = IDYES then
    AppRunning(Dir, True)
  else
    Result := False;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if DirExists(ExpandConstant('{app}')) and not AskClose(ExpandConstant('{app}')) then
    Result := 'Закрой Twitch TTS и запусти установку ещё раз.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Flag: String;
begin
  { ярлык делает установщик — install.ps1 второй делать не будет }
  if CurStep = ssPostInstall then begin
    Flag := ExpandConstant('{app}\data\shortcut.flag');
    if not FileExists(Flag) then SaveStringToFile(Flag, 'done', False);
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := AskClose(ExpandConstant('{app}'));
  if not Result then Exit;
  if UninstallSilent then
    KeepSettings := Pos('/DELETEALL', Uppercase(GetCmdTail)) = 0
  else
    KeepSettings := MsgBox('Оставить настройки и вход в Twitch?' + #13#10#13#10 +
      '«Да» — останутся config.json и папка data (словари, списки, муты): при новой установке в ту же папку всё вернётся.' + #13#10 +
      '«Нет» — удалить всё.' + #13#10#13#10 +
      'Python, библиотеки и голоса удаляются в любом случае.', mbConfirmation, MB_YESNO) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  App, Name: String;
  F: TFindRec;
begin
  if CurUninstallStep <> usPostUninstall then Exit;
  App := ExpandConstant('{app}');
  if not KeepSettings then begin
    DelTree(App, True, True, True);
    Exit;
  end;
  { всё, что докачали и добавили обновления, кроме настроек }
  if FindFirst(App + '\*', F) then
    try
      repeat
        Name := F.Name;
        if (Name <> '.') and (Name <> '..') and (CompareText(Name, 'config.json') <> 0) and (CompareText(Name, 'data') <> 0) then begin
          if F.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
            DelTree(App + '\' + Name, True, True, True)
          else
            DeleteFile(App + '\' + Name);
        end;
      until not FindNext(F);
    finally
      FindClose(F);
    end;
end;
