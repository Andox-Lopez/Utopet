; ============================================================================
;  Utopet 桌宠 —— Inno Setup 安装脚本
;  Utopet Desktop Pet — Inno Setup script
; ----------------------------------------------------------------------------
;  编译 / build:
;     ISCC.exe installer\Utopet.iss
;
;  产物 / output:
;     output\Utopet-Setup-1.0.5.exe
;
;  依赖：先跑 tools\build_release.py 生成 dist\Utopet\（本脚本不自己构建）
;  Requires: run tools\build_release.py first to produce dist\Utopet\
;
;  ⚠️ characters 目录**只打包 Miku**（默认角色），其余角色不进安装包。
;     用户可自行把 Ayaka / 花卷等角色包丢进 characters\，设置里即可切换。
;     Only Miku (the default) is bundled; users drop other packs into characters\.
;
;  ⚠️ 1.0.3 起本程序曾用名 Shimeji。安装时会自动检测旧版并迁移：先把旧版的
;     data\（设置）与 characters\（用户加的角色）备份到临时目录，卸载旧版，
;     再把备份搬进新目录。AppId 保持不变，否则 Windows 会当成两个独立程序，
;     旧版会永远留在「应用和功能」里。
; ============================================================================

#define AppName "Utopet 桌宠"
#define AppNameEn "Utopet Desktop Pet"
#define AppVersion "1.1.2"
#define AppPublisher "Utopet"
#define AppExeName "Utopet.exe"
; 与 1.0.x 保持同一个 GUID：这是同一个产品的升级，改 GUID 会让旧版变成
; 「另一个程序」留在应用列表里，用户还得手动去卸载。
; Same GUID as 1.0.x: this is an upgrade of the same product.  Changing it would
; leave the old build stranded in Apps & Features.
#define AppId "{{8E7C4B1A-9D2F-4A63-B5E8-1C7F3D6A2B90}"

; 旧版安装目录 / where 1.0.x installed itself
#define OldAppDir "{commonpf}\Shimeji"
#define OldAppExe "Shimeji.exe"

; 「仅为我安装」模式下 Utopia 会落在这里。1.0.5 起不再提供该模式，
; 但已经被那种安装方式分流出去的那一份需要找回来，否则它会一直留在原地，
; 用户以为在用A 其实启动的是 B。
; Where a per-user install landed. 1.0.5 no longer offers that mode, but any
; copy already stranded there has to be brought back, otherwise it lingers
; and the user ends up launching the wrong build without noticing.
#define UserAppDir "{localappdata}\Programs\Utopet"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
; 卸载器在「应用和功能」和卸载窗口标题里显示的名字。
; 不写的话 Inno 用默认的「卸载 {app}」—— 而 {app} 在卸载阶段还没展开，
; 用户看到的就是字面量「卸载{app}」，像是程序没读到自己叫什么。
; The name shown in Apps & Features and in the uninstall window title.
; Left unset, Inno falls back to "卸载 {app}", but {app} is not expanded at
; that point, so the user literally sees "卸载{app}".
UninstallDisplayName=卸载 {#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppComments=桌面宠物 / Desktop mascot — Python + PySide6 重制版
DefaultDirName={autopf}\Utopet
DefaultGroupName={#AppName}
; ⚠️ DisableDirPage 必须显式写 no。
;   不写走的是 auto：**注册表里查到同 AppId 已安装，就整页不显示** ——
;   「选择安装位置」连同路径输入框和「浏览…」一起消失，用户完全没法改路径
;   （现象：第二次装同一个程序时目录页不见了，只剩默认路径）。
;   官方原文：「If this is set to auto ... it will not show the Select
;   Destination Location wizard page. If the page is not shown, it will always
;   use the default directory name.」
;   这里是 1.0.5→1.0.6 升级，用户最可能想改的就是安装位置（Program Files 要
;   管理员权限、常有人想装到 D 盘），所以宁可每次都给。
DisableDirPage=no
DisableProgramGroupPage=auto
; ⚠️ 不要开 PrivilegesRequiredOverridesAllowed=dialog。
;   开了之后向导会问「为所有用户安装 / 仅为我安装」，两者的差别是致命的：
;     管理员模式 → 装到 {commonpf}，卸载记录写 HKLM
;     用户模式   → 装到 {localappdata}\Programs，卸载记录写 HKCU
;   Inno 靠读自己那条卸载记录（InstallLocation）来记住上次的安装目录。
;   一旦两次安装的范围不同，它读到的那条记录与实际模式对不上，
;   路径记忆直接失效 —— 实测就是向导退回默认目录、程序另起一份到
;   C 盘，而旧那份还留在原地。
;   固定成管理员安装，两种模式的分叉从源头掐掉。
; Do NOT enable PrivilegesRequiredOverridesAllowed.  It offers an
; all-users / current-user choice, and the two modes are irreconcilable:
; admin installs to {commonpf} with the uninstall record under HKLM, while
; per-user installs to {localappdata}\Programs with the record under HKCU.
; Inno recovers the previous directory by reading that very record, so a
; scope switch makes the memory fail — the wizard falls back to the default
; directory and a second copy lands elsewhere while the old one stays put.
; Pinning it to admin removes the fork at the source.
UsePreviousAppDir=yes
OutputDir=..\output
OutputBaseFilename=Utopet-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
SetupIconFile=..\shimeji\assets\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
; 需要管理员才能装到 Program Files / needs admin for Program Files
; 固定管理员，不再允许用户降级成 per-user（原因见上面 DefaultDirName 那段注释）。
; Admin-only; per-user is no longer offered (see the DefaultDirName note above).
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
; VersionInfoVersion 必须是四段数字（Windows 版本资源不认 1.0.7-2 这种写法），
; 而 AppVersion 可以是 1.0.7-2 —— 两者分开写，别共用同一个宏。
; VersionInfoVersion must be four numeric parts (Windows version resources
; reject "1.0.7-2"); AppVersion may carry the suffix.  Keep them separate.
VersionInfoVersion=1.1.2.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; 用相对路径而不是 compiler:Languages\... —— 官方没提供简体中文，那个目录里根本没有
; 这个文件。放在 installer\ 下，项目自包含，换台机器编译也不会找不到。
; Relative path, not compiler:Languages\: Inno ships no Simplified Chinese, so
; that file simply isn't there.  Keeping it next to this script makes the
; project self-contained.
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; 刻意不提供「开机自启」安装任务：{userstartup} 是 per-user 区域，而本脚本用
; admin 权限装到 Program Files，两者语义冲突（IS 会警告）。程序设置面板里
; 已经有「开机自启」开关（写 HKCU Run 项），功能上重复。
; No launch-at-startup task here: {userstartup} is a per-user area while we
; install to Program Files with admin rights, and Inno warns about mixing
; them.  The app's own settings dialog already offers launch-at-login (HKCU Run).

[Files]
; --- 主程序 + Qt 运行库（dist\Utopet 全部内容，除 characters）---
Source: "..\dist\Utopet\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "characters\*"

; --- 角色：只放 Miku（默认角色）---
; 迁移在 ssPostInstall 阶段做（晚于本节），所以用户改过的 Miku 不会被包里
; 的版本盖回去；这里 overwrite 与否都无所谓，两层都设上以防将来调整顺序。
; Migration runs at ssPostInstall, i.e. *after* this section, so a user-modified
; Miku is never clobbered by the bundled copy.
Source: "..\characters\Miku\*"; DestDir: "{app}\characters\Miku"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; 用户自己加的角色放这里 / where users drop extra character packs.
; uninsneveruninstall 让卸载时保留这个目录 —— 用户额外下载的角色不会被删掉。
; 代价：卸载后可能留一个空的 characters\ 目录，由下面的代码补掉。
Name: "{app}\characters"; Flags: uninsneveruninstall

[UninstallDelete]
; data\ 与 config\ 是程序运行期在 {app} 下自己创建的（设置、日志、缓存），
; **没有**被 Files/Dirs 登记，卸载器因此不认识它们，不删就会留个空壳目录在
; Program Files 里。settings.json 这类用户配置也随之清掉 —— 卸载即重置，
; 需要保留配置的用户自己备份。
; data\ and config\ are created by the app at run time and are never registered
; with Files/Dirs, so the uninstaller leaves an empty shell behind otherwise.
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\config"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  OldInstallFound: Boolean;
  MigrateFound: Boolean;
  BackupDir: String;

{ 递归复制：目标已存在就跳过，不覆盖。
  这一点是迁移逻辑的核心 —— 用户改过的角色/图片必须赢过包里那份。
  Recursive copy that never overwrites: a user-edited pack or image always
  wins over the bundled copy. }
{ 递归复制，**不覆盖已存在的文件**。
  这一点是迁移逻辑的核心 —— 用户改过的角色/图片必须赢过包里那份。

  刻意用 robocopy 而不是 Pascal 的 FileCopy：本机的 ISCC 对 FileCopy 的参数
  解析有问题（任何参数个数都报 "Invalid number of parameters"），而 robocopy
  恰好有现成的 /XC /XN /XO 三个开关组合可以表达「只补缺失的，不动已有的」。
  robocopy 的退出码 <8 都算成功。

  Recursive copy that never overwrites: a user-edited pack or image always wins
  over the bundled copy.

  robocopy rather than Pascal's FileCopy on purpose: this ISCC build mis-parses
  FileCopy's arguments (every arity reports "Invalid number of parameters"),
  while robocopy has /XC /XN /XO which together mean exactly "fill in what's
  missing, leave what's already there alone".  Exit codes below 8 are success. }
procedure CopyTreeNoOverwrite(Src, Dst: String);
var
  ResultCode: Integer;
begin
  if not DirExists(Src) then
    Exit;
  { /E 子目录 / recurse     /XC 跳过已存在（同大小）
    /XN 跳过源较新          /XO 跳过源较旧
    三个合起来 = 只补缺失的文件，绝不覆盖 }
  Exec(ExpandConstant('{sys}\robocopy.exe'),
       ' "' + Src + '" "' + Dst + '" /E /XC /XN /XO /NFL /NDL /NJH /NJS /R:1 /W:1',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

{ 递归删除。旧版卸载后目录里常有 unins000.exe 之类删不掉的残留。
  用 rmdir /s /q 而不是逐文件删：unins000.exe 常在运行，必须整目录强删。
  Recursive delete via rmdir /s /q: unins000.exe is often *running* right after
  the uninstaller returns, and it can only be removed as part of the tree. }
procedure RemoveTree(Dir: String);
var
  ResultCode: Integer;
begin
  if not DirExists(Dir) then
    Exit;
  Exec(ExpandConstant('{sys}\cmd.exe'),
       '/c rmdir /s /q "' + Dir + '"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

{ 把备份里的 characters 搬进新目录。
  现在 CopyTreeNoOverwrite 已经保证不覆盖，整目录一次搬过去即可 ——
  逐个子目录遍历反而多余（当初那么写是因为 FileCopy 只能一次一个文件）。
  One call is enough now: the no-overwrite rule is a robocopy flag now. }
procedure RestoreCharacters(DestDir: String);
begin
  CopyTreeNoOverwrite(BackupDir + '\characters', DestDir);
end;

{ 找一个目录里的卸载器并静默跑掉。
  「应用和功能」里的条目要正规清掉，所以必须调它自己的 unins，不能只删文件。
  跑之前先结束正在运行的 exe —— 它自己锁着文件。

  Find and silently run a directory's uninstaller.
  The Apps & Features entry has to go through its own uninstaller; deleting
  files by hand would leave a stale entry behind.  End the running exe first
  because it holds its own files open. }
procedure RunUninstaller(Dir: String);
var
  UninsRec: TFindRec;
  Unins: String;
  ResultCode: Integer;
begin
  Unins := '';
  if FindFirst(Dir + '\unins*.exe', UninsRec) then
  begin
    Unins := UninsRec.Name;
    FindClose(UninsRec);
  end;
  if Unins = '' then
    Exit;
  Exec(Dir + '\' + Unins, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

{ 处理「仅为我安装」遗留下来的那一份。
  先备份再卸载再删目录，三步都不能省：per-user 安装的 data\ 里存着设置，
  卸载器会把它一起删掉。

  备份优先级：管理员安装那份先备份，per-user 后备份，而CopyTreeNoOverwrite
  不覆盖，所以**管理员那份赢**。这不是任意的 —— 用户原本就在用管理员那份，
  per-user 是升级失败后凭空多出来的副本，把它的配置当权威会让用户看到
  「设置被重置」。

  Handle the copy stranded by a per-user install: back up, uninstall, delete.
  The admin install is backed up first and the copy never overwrites, so the
  admin build wins.  That is deliberate: the admin build is the one the user
  was actually running, and the per-user copy is a phantom created by the
  failed upgrade — treating its settings as authoritative would look like the
  user's configuration had been reset. }
procedure MigrateUserScopedCopy;
var
  UserDir: String;
  ResultCode: Integer;
begin
  UserDir := ExpandConstant('{#UserAppDir}');
  if not DirExists(UserDir) then
    Exit;
  { 不能只看 exe 在不在：用户手滑删了 exe、或杀软 quarantined 了它，
    恰恰是这种「装了一半」的目录里还留着 data\ —— 而那正是最该救的东西。
    所以只要exe 或 data\ 任意一个在，就当它是残留。
    Don't require the exe: a half-broken install (exe deleted by the user or
    quarantined by AV) is exactly the case that still holds data\, which is
    the thing worth rescuing.  Either marker is enough. }
  if not FileExists(UserDir + '\' + ExpandConstant('{#AppExeName}')) and
     not DirExists(UserDir + '\data') then
    Exit;

  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM ' +
       ExpandConstant('{#AppExeName}'), '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);

  CopyTreeNoOverwrite(UserDir + '\data', BackupDir + '\data');
  CopyTreeNoOverwrite(UserDir + '\config', BackupDir + '\config');
  CopyTreeNoOverwrite(UserDir + '\characters', BackupDir + '\characters');

  RunUninstaller(UserDir);
  RemoveTree(UserDir);
end;

{ 安装前探测并迁移旧版。
  必须在新文件写进安装目录之前做完：等新目录里已经有东西，再动旧目录就晚了。

  Detect and migrate the old build *before* installing: once files land in the
  new directory it is too late to move anything out of the old one. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  OldDir: String;
  ResultCode: Integer;
begin
  Result := '';
  OldDir := ExpandConstant('{#OldAppDir}');
  BackupDir := ExpandConstant('{tmp}\Utopet_Migrate');
  OldInstallFound := False;
  MigrateFound := False;

  { 已经是 Utopet，无需迁移 }
  if FileExists(ExpandConstant('{app}\' + ExpandConstant('{#AppExeName}'))) then
    Exit;

  { per-user 残留要先处理：即使没装过 Shimeji 时代，它也可能单独存在。
    而且要在 Shimeji 迁移之前做 —— 那一步会重建备份目录，把这里的成果抹掉。 }
  RemoveTree(BackupDir);
  CreateDir(BackupDir);
  MigrateUserScopedCopy;
  if DirExists(BackupDir + '\data') or DirExists(BackupDir + '\characters')
     or DirExists(BackupDir + '\config') then
    MigrateFound := True;

  if not DirExists(OldDir) then
    Exit;
  if not FileExists(OldDir + '\' + ExpandConstant('{#OldAppExe}')) then
    Exit;

  OldInstallFound := True;

  { 旧版可能还在跑：文件被占用，复制到一半会得到残缺的备份。
     直接结束它 —— 桌宠只在用户改设置时才落盘，没有需要保护的写缓存。
     The old build may still be running: its files are locked and the backup
     would come out truncated.  End it — the pet only writes to disk when the
     user saves settings, so there is no cache worth protecting. }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM ' +
       ExpandConstant('{#OldAppExe}'), '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);

  { 1) 先备份再卸载，顺序不能反 —— 旧版卸载器会删掉它自己的 data 目录。 }
  CopyTreeNoOverwrite(OldDir + '\data', BackupDir + '\data');
  CopyTreeNoOverwrite(OldDir + '\config', BackupDir + '\config');
  CopyTreeNoOverwrite(OldDir + '\characters', BackupDir + '\characters');

  { 2) 跑旧版卸载器，这样「应用和功能」里的条目也被正规清掉。 }
  RunUninstaller(OldDir);

  { 3) 卸载器删不掉的（它自己的 exe、被占用的日志）直接清掉 }
  if DirExists(OldDir) then
    RemoveTree(OldDir);

  MigrateFound := True;
end;

{ 安装完成后把备份搬回来。
  Restore the backup once the new files are in place.
  条件是 MigrateFound 而不是 OldInstallFound：per-user 残留那条路径不会设
  后者，但备份已经搬出去了，不搬回来等于把用户的设置丢了。 }
procedure CurStepChanged(CurStep: TSetupStep);
var
  Answer: Integer;
  ResultCode: Integer;
  Msg: String;
begin
  if (CurStep = ssPostInstall) and MigrateFound then
  begin
    { data\：直接合并。新版本的默认值会补齐缺失的键（Settings.load 就是合并
      语义），所以旧配置里没有的新选项会自动出现。 }
    CopyTreeNoOverwrite(BackupDir + '\data', ExpandConstant('{app}\data'));
    CopyTreeNoOverwrite(BackupDir + '\config', ExpandConstant('{app}\config'));
    RestoreCharacters(ExpandConstant('{app}\characters'));
  end;
  if (CurStep = ssPostInstall) then
    RemoveTree(BackupDir);

  if (CurStep = ssPostInstall) and (not WizardSilent) then
  begin
    { 按当前向导语言显示，避免给英文语言包也塞一份中文自定义文案
      （IS 会警告 "custom message not defined for english"）。
      Pick the text by language so the English install stays English. }
    if OldInstallFound and (ActiveLanguage = 'chinesesimplified') then
      Msg := '安装完成。已保留旧版的设置与角色。' + #13#10 + '现在启动桌宠吗？'
    else if OldInstallFound then
      Msg := 'Setup finished. Your settings and characters were kept.' + #13#10 +
             'Launch the desktop pet now?'
    else if ActiveLanguage = 'chinesesimplified' then
      Msg := '安装完成。现在启动桌宠吗？'
    else
      Msg := 'Setup finished. Launch the desktop pet now?';

    Answer := MsgBox(Msg, mbConfirmation, MB_YESNO);
    if Answer = IDYES then
      ShellExec('open', '{app}\' + ExpandConstant('{#AppExeName}'), '', '',
                SW_SHOWNORMAL, ewNoWait, ResultCode);
  end;
end;

{ 卸载收尾：如果 characters\ 里没有用户额外加的角色了（只剩空目录），
  就把它删掉，避免卸载完在 Program Files 里留个空壳目录。

  上面 Dirs 节里给 characters 设了 uninsneveruninstall（保护用户自己加的角色），
  代价就是空目录会留下，这里补掉。

  注意：注释里**不能出现方括号包起来的节名**，Pascal 编译器会把它当成节标签，
  直接报 "Invalid section tag"。

  Clean up: characters\ is marked uninsneveruninstall so users' own packs
  survive, which leaves an empty shell behind.  Remove it when it is empty. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  CharsDir: String;
  FindRec: TFindRec;
  HasFiles: Boolean;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    CharsDir := ExpandConstant('{app}\characters');
    if DirExists(CharsDir) then
    begin
      HasFiles := False;
      if FindFirst(CharsDir + '\*', FindRec) then
      begin
        try
          repeat
            if (FindRec.Name <> '.') and (FindRec.Name <> '..') and
               (FindRec.Attributes <> FILE_ATTRIBUTE_DIRECTORY) then
            begin
              HasFiles := True;
              Break;
            end;
          until not FindNext(FindRec);
        finally
          FindClose(FindRec);
        end;
      end;
      if not HasFiles then
        RemoveDir(CharsDir);
    end;

    { 最后把安装目录本身删掉。
      「卸载完 Program Files 里还留一个空的 Utopet 文件夹」这个 bug 一直
      没被抓到，是因为验证脚本把「目录还在但内容为空」和「目录不存在」
      混为一谈：os.listdir 对空目录返回空列表，而 not 空列表为真，
      空目录就直接通过了检查。断言写法本身要一起修。

      Inno 自己不会删安装目录 —— characters 标了 uninsneveruninstall，
      卸载器认为这棵树「非空 / 受保护」，于是连父目录也留着。
      这里用 RemoveDir 而不是 rmdir /s /q：RemoveDir 在目录非空时**失败**，
      所以用户自己下载的角色还在时它什么都不会做，绝不会误删用户数据。
      rmdir /s 是会连内容一起删的 —— 那是绝对不能用的写法。

      注意：注释里不能出现大括号包起来的节名，Pascal 编译器会把它当成
      注释的开头，直接报语法错（写这段时就踩了一次）。

      Remove the install directory itself.  Inno leaves it behind because
      characters\ carries uninsneveruninstall, which makes the uninstaller
      treat the tree as non-empty.  RemoveDir (not rmdir /s) is the safe call:
      it FAILS on a non-empty directory, so a user who still has downloaded
      character packs keeps everything.  }
    RemoveDir(ExpandConstant('{app}'));
  end;
end;
