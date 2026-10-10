# 資料夾刪不掉時的診斷與安全移除。
# 設計原則：
#   1. 預設只「看」，不動任何東西。要動一定先問。
#   2. 🔴 絕不碰這個資料夾以外的任何東西。不改桌面 ACL、不動 OneDrive、
#      不關防毒、不做遞迴 takeown。
#   3. 每一步都印出結果，使用者可以直接截圖回報。

param([string]$Target)

$ErrorActionPreference = 'Continue'
$OutputEncoding = [Console]::OutputEncoding

# 🔴 絕對不能讓這支程式的工作目錄留在要刪的資料夾裡面。
#    Windows 不允許改名或刪除「某個行程的目前目錄」，那會讓救援必定失敗，
#    而且失敗訊息看起來像權限問題，把人帶去改 ACL 的歧路。
#    （2026-09-08 出貨前稽核實測抓到：舊版會刪光資料夾內所有檔案才失敗。）
Set-Location -LiteralPath $env:TEMP

function Line($c = '-') { Write-Host ($c * 66) -ForegroundColor DarkGray }
function Head($t) { Write-Host ''; Line '='; Write-Host "  $t" -ForegroundColor White; Line '=' }

if ($Target) {
    $target = $Target.TrimEnd('\')
} else {
    # 沒帶參數時（例如有人直接執行這支 .ps1）才自己推算
    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    $target = Split-Path -Parent $here      # scripts\ 的上一層 = 程式資料夾
}

Write-Host ''
Write-Host '  TIO Voice Genie — rescue tool for a folder that will not delete' -ForegroundColor Cyan
Line '='
Write-Host "  Target folder: $target"
Write-Host ''
Write-Host '  By default this tool only CHECKS; it does not delete anything.' -ForegroundColor Yellow
Write-Host '  It never touches any file outside this folder.' -ForegroundColor Yellow

# ───────────────────────── 1. 基本狀態 ─────────────────────────
Head '1. Current state of this folder'
if (-not (Test-Path -LiteralPath $target)) {
    Write-Host '  The folder no longer exists. Nothing to do.' -ForegroundColor Green
    Read-Host '  Press Enter to close'
    exit 0
}
$item = Get-Item -LiteralPath $target -Force
Write-Host "  Created    : $($item.CreationTime)"
Write-Host "  Attributes : $($item.Attributes)"
$files = @(Get-ChildItem -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue)
Write-Host "  Contains   : $($files.Count) items"
$ro = @($files | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReadOnly })
Write-Host "  Read-only  : $($ro.Count) files"
if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    Write-Host '  ⚠ This is a link / OneDrive placeholder, not an ordinary folder' -ForegroundColor Yellow
}

# ───────────────────────── 2. 擁有者與權限 ─────────────────────────
Head '2. Owner and permissions (please screenshot this part)'
try {
    $acl = Get-Acl -LiteralPath $target
    Write-Host "  Owner : $($acl.Owner)"
    Write-Host "  Signed in as : $env:USERDOMAIN\$env:USERNAME"
    Write-Host ''
    Write-Host '  Permission entries:'
    foreach ($a in $acl.Access) {
        $inh = if ($a.IsInherited) { 'inherited' } else { 'set directly' }
        Write-Host ("    {0,-38} {1,-8} {2}" -f $a.IdentityReference, $a.AccessControlType, $inh)
        Write-Host ("        {0}" -f $a.FileSystemRights) -ForegroundColor DarkGray
    }
    # 判斷「我到底有沒有權限」時，這幾種都算數：
    #   直接列出我的帳號 / Users / Authenticated Users
    #   OWNER RIGHTS、CREATOR OWNER —— 只要我就是擁有者，這兩個就等於我
    # 🔴 漏掉 OWNER RIGHTS 會誤報成「ACL 問題」，把人帶去改權限的歧路。
    $iAmOwner = ($acl.Owner -like "*$env:USERNAME")
    $mine = @($acl.Access | Where-Object {
        $_.AccessControlType -eq 'Allow' -and (
            $_.IdentityReference -like "*\$env:USERNAME" -or
            $_.IdentityReference -like '*Users' -or
            $_.IdentityReference -like '*Authenticated Users' -or
            $_.IdentityReference -like '*Everyone' -or
            ($iAmOwner -and ($_.IdentityReference -like '*OWNER RIGHTS' -or
                             $_.IdentityReference -like '*CREATOR OWNER'))
        )
    })
    $denies = @($acl.Access | Where-Object { $_.AccessControlType -eq 'Deny' })
    Write-Host ''
    Write-Host ("  Are you the owner : " + $(if ($iAmOwner) { 'yes' } else { 'no' }))
    if ($denies.Count -gt 0) {
        Write-Host '  🔴 There are "Deny" rules, and they override any Allow rule:' -ForegroundColor Red
        $denies | ForEach-Object { Write-Host "     $($_.IdentityReference)  $($_.FileSystemRights)" }
    }
    if ($mine.Count -eq 0 -and -not $iAmOwner) {
        Write-Host '  🔴 You are not the owner and you are not in the permission list — looks like an ACL problem' -ForegroundColor Red
    } elseif ($denies.Count -gt 0) {
        Write-Host '  🔴 A Deny rule is in the way — looks like an ACL problem' -ForegroundColor Red
    } else {
        Write-Host '  ✅ Permissions look fine — so if it will not delete, something is most likely holding it; it is not a permissions problem' -ForegroundColor Green
        Write-Host '     (in that case it usually deletes fine after a restart)'
    }
} catch {
    Write-Host "  Could not read the permissions: $($_.Exception.Message)" -ForegroundColor Red
}

# ───────────────────────── 3. 誰鎖住它 ─────────────────────────
Head '3. Is any program using it?'
$holders = @()
try {
    $procs = Get-Process -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        $path = $null
        try { $path = $p.Path } catch {}
        if ($path -and $path.StartsWith($target, [StringComparison]::OrdinalIgnoreCase)) {
            $holders += "$($p.ProcessName) (PID $($p.Id))  ← its program file is in this folder"
        }
    }
    # 用 WMI 查每個程序的工作目錄（cwd 在資料夾裡就會鎖住它）
    # 🔴 排除「這支救援程式自己」以及啟動它的 cmd —— 否則它會把自己列成兇手，
    #    使用者看到 powershell.exe / cmd.exe 只會更困惑。
    $selfIds = @($PID)
    try {
        $me = Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction SilentlyContinue
        if ($me -and $me.ParentProcessId) { $selfIds += [int]$me.ParentProcessId }
    } catch {}
    $cim = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
           Where-Object { $_.CommandLine -and $_.CommandLine -like "*$target*" -and
                          $selfIds -notcontains $_.ProcessId }
    foreach ($c in $cim) {
        $holders += "$($c.Name) (PID $($c.ProcessId))  ← its command line mentions this folder"
    }
} catch {}
# 🔴 最常見的原因：檔案總管本身開著這個資料夾。
# explorer.exe 的執行檔路徑和指令列都不會提到該資料夾，所以上面那種找法
# 抓不到它 —— 一定要另外列舉「開著的檔案總管視窗」才看得見。
# （2026-09-07 實證：同事那台刪不掉，原因就是這個。）
$script:explorerWins = @()
try {
    $sh = New-Object -ComObject Shell.Application
    foreach ($w in $sh.Windows()) {
        $loc = $null
        try { $loc = $w.Document.Folder.Self.Path } catch {}
        if ($loc -and ($loc -eq $target -or $loc.StartsWith($target + '\',
                       [StringComparison]::OrdinalIgnoreCase))) {
            $script:explorerWins += $w
            $holders += "File Explorer window, currently open at: $loc"
        }
    }
} catch {}

if ($holders.Count -gt 0) {
    Write-Host '  🔴 Found things that are using this folder:' -ForegroundColor Red
    $holders | Select-Object -Unique | ForEach-Object { Write-Host "     $_" }
    Write-Host ''
    if ($script:explorerWins.Count -gt 0) {
        Write-Host '  ⭐ A File Explorer window has this folder open — that is the most common cause.' -ForegroundColor Yellow
        Write-Host '     Close that window (or switch it to another folder) and delete again; that usually does it.' -ForegroundColor Yellow
    } else {
        Write-Host '  → Close these first (or just restart) and delete again; that usually does it.' -ForegroundColor Yellow
    }
} else {
    Write-Host '  ✅ No program found that is obviously holding it' -ForegroundColor Green
    Write-Host '     (OneDrive or antivirus holding files in the background cannot be detected;'
    Write-Host '      also: if you have "clicked into" this folder, File Explorer may still remember it,'
    Write-Host '      so switch to another folder or close the window and try again)'
}

# ───────────────────────── 4. 建議 ─────────────────────────
Head '4. Suggested order of steps'
Write-Host '  Try them in this order, safest first:'
Write-Host ''
Write-Host '   (1) ⭐ Close any File Explorer window that has this folder open, and every black'
Write-Host '       window of this tool, then delete again.'
Write-Host '       (in real cases this step alone fixed it — the folder was simply open)'
Write-Host '   (2) Still no luck → restart, and delete it as the very first thing after restarting.'
Write-Host '       ⭐ This step is also a diagnosis: if it deletes after a restart, a program was'
Write-Host '          holding it, not a permissions problem.'
Write-Host '   (3) Still no luck → try the "safe removal" below.'
Write-Host '   (4) Nothing works → screenshot section 2 above and send it together with this screen.'
Write-Host ''
# 🔴 不要斷言「這個資料夾在 OneDrive 裡面」。那是開發這台電腦的情況，
#    同事的資料夾可能在 D 槽、隨身碟或網路磁碟，講錯會讓人以為工具在亂講。
if ($Target -like '*OneDrive*') {
    Write-Host '  ⚠ Websites will tell you to change permissions with takeown / icacls — this folder is'  -ForegroundColor Yellow
    Write-Host '    inside OneDrive, where that could affect other synced files, so this tool does not do it.'          -ForegroundColor Yellow
} else {
    Write-Host '  ⚠ Websites will tell you to change permissions with takeown / icacls — that changes the owner'  -ForegroundColor Yellow
    Write-Host '    and permissions of the whole folder, a bigger risk than the problem it solves, so this tool does not do it.'              -ForegroundColor Yellow
}

# ───────────────────────── 5. 安全移除 ─────────────────────────
Head '5. Try "safe removal" now?'
Write-Host '  It does these three things, all limited to this folder:'
Write-Host '    a. Removes the "read-only" attribute from the files inside'
Write-Host '    b. First renames the folder into a holding area (if the rename works = no permission problem)'
Write-Host '    c. Deletes the files one by one and lists any that cannot be deleted'
Write-Host ''
$ans = Read-Host '  Try it? Type Y and press Enter (Enter alone = no)'
if ($ans -notmatch '^[Yy]') {
    Write-Host ''
    Write-Host '  Nothing was changed.' -ForegroundColor Green
    Read-Host '  Press Enter to close'
    exit 0
}

Head 'Working'
if ($script:explorerWins.Count -gt 0) {
    Write-Host "  0. First closing $($script:explorerWins.Count) File Explorer window(s) that have this folder open…"
    foreach ($w in $script:explorerWins) { try { $w.Quit() } catch {} }
    Start-Sleep -Milliseconds 1200
    Write-Host '     Closed'
}
Write-Host '  a. Clearing the read-only attribute…'
$cleared = 0
foreach ($f in $files) {
    if ($f.Attributes -band [IO.FileAttributes]::ReadOnly) {
        try { $f.Attributes = $f.Attributes -bxor [IO.FileAttributes]::ReadOnly; $cleared++ } catch {}
    }
}
Write-Host "     Cleared $cleared"

Write-Host '  b. Trying to rename it into the holding area…'
# 🔴 暫存區必須跟目標同一個磁碟，不能用 %TEMP%。
#    跨磁碟的 Move-Item 是「逐檔複製再刪除」，中途卡住會變成
#    「一半的檔已經被搬走，卻回報失敗」，比不動更糟。
#    （2026-09-10：uninstall_gui.py 先修好，這支漏了，是同一個病。）
#    🔴 2026-10-10 更正：同磁碟的 Move-Item **也不是**單純改名。裡面有東西被別的
#    程式開著（檔案被開著，不管有沒有帶 FILE_SHARE_DELETE；或某個行程的工作目錄
#    停在裡面的子資料夾）時整個改名會失敗，Windows PowerShell 5.1 的 Move-Item
#    接著改成一個一個檔搬，搬到搬不動的那一個才丟例外 → 一樣拆成兩半（實測：鎖 1 個
#    檔，12～28 個檔跑進 _gs_delete_…；工作目錄停在 scripts\ 時 32 個檔全跑掉），
#    下面卻印「沒有刪除任何檔案」。所以改用 [IO.Directory]::Move：只做真正的改名，
#    要嘛整個成功、要嘛完全不動；跨磁碟時直接丟例外，不會退回逐檔複製。
#    取捨：檔案被「允許刪除」的方式開著時（防毒、索引、雲端同步常這樣開），舊寫法
#    逐檔搬會碰巧整個成功；新寫法先每秒再試、最多試 5 次（見下面），還是被佔用就整個
#    不動——寧可不動，也不要拆成兩半。
$staged = Join-Path (Split-Path -Parent $target) ("_gs_delete_" + [Guid]::NewGuid().ToString('N').Substring(0, 8))
$moved = $false
try {
    # 🔴 2026-10-10（使用者裁決）：改名失敗先隔 1 秒再試，最多試 5 次（約多等 4 秒）——防毒、索引、
    #    雲端同步、剛關掉的檔案總管常常只佔用幾秒。改名是全有全無，重試不會拆成兩半；5 次都不行才
    #    把例外往外丟，走下面的 catch。
    for ($attempt = 1; ; $attempt++) {
        try { [IO.Directory]::Move($target, $staged); break }
        catch { if ($attempt -ge 5) { throw $_ }; Start-Sleep -Milliseconds 1000 }
    }
    $moved = $true
    Write-Host '     ✅ Renamed — the folder is no longer under its original name (it is temporarily called _gs_delete_…, and its contents are deleted one by one next)' -ForegroundColor Green
    Write-Host '        (so it is not a permissions problem; something is just holding the contents)'
} catch {
    # 🔴 2026-10-10：這裡不印 $_.Exception.Message。改用 [IO.Directory]::Move 之後它是
    #    「以 "2" 引數呼叫 "Move" 時發生例外狀況: "拒絕存取路徑 '…'。"」——技術雜訊，「拒絕存取」
    #    又會把人帶去以為是權限問題（這支工具最想避免的歧路）。使用者裁決：只留白話。
    Write-Host '     ✗ Could not move it: Windows would not let this folder be renamed.' -ForegroundColor Red
    Write-Host '        This means a program is still holding this folder (not a permissions problem).' -ForegroundColor Yellow
    Write-Host ''
    # 🔴 這裡絕對不能往下走去逐檔刪除。
    #    舊版會在改名失敗後照樣刪光裡面所有檔案（含手冊和解除安裝程式），
    #    結果是「資料夾仍然刪不掉，但東西全沒了」，比不動更糟。
    Write-Host '  To be safe, no files were deleted.' -ForegroundColor Green
    Write-Host '  Please do this:' -ForegroundColor Yellow
    Write-Host '    1. Close every File Explorer window and every black window of this tool'
    Write-Host '    2. Restart, and delete this folder as the very first thing after restarting'
    Write-Host '    3. If it still fails, screenshot sections 2 and 3 above and send them in'
    Write-Host ''
    Read-Host '  Press Enter to close'
    exit 0
}

Write-Host '  c. Deleting one by one…'
$failed = @()
Get-ChildItem -LiteralPath $staged -Recurse -Force -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | ForEach-Object {
        try { Remove-Item -LiteralPath $_.FullName -Force -Recurse -ErrorAction Stop }
        catch { $failed += "$($_.FullName)" }
    }
try { Remove-Item -LiteralPath $staged -Force -Recurse -ErrorAction Stop } catch { $failed += $staged }

Head 'Result'
if ($failed.Count -eq 0) {
    Write-Host '  ✅ Everything was deleted.' -ForegroundColor Green
} elseif ($moved) {
    Write-Host '  ✅ The original folder is gone (which is what you wanted).' -ForegroundColor Green
    Write-Host "  ⚠ But $($failed.Count) file(s) still could not be deleted and were left in this holding folder:" -ForegroundColor Yellow
    Write-Host "     $staged"
    Write-Host '     It will not go away by itself: after restarting, just delete this folder in File Explorer.'
} else {
    Write-Host "  ✗ $($failed.Count) item(s) could not be deleted:" -ForegroundColor Red
    $failed | Select-Object -First 12 | ForEach-Object { Write-Host "     $_" }
    Write-Host ''
    Write-Host '  Please restart and run this tool again; if it still fails, screenshot this screen and send it in.' -ForegroundColor Yellow
}
Write-Host ''
Read-Host '  Press Enter to close'
