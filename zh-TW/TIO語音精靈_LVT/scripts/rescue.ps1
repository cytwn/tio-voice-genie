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
Write-Host '  TIO語音精靈 — 資料夾刪不掉時的救援工具' -ForegroundColor Cyan
Line '='
Write-Host "  對象資料夾：$target"
Write-Host ''
Write-Host '  這支程式預設「只檢查、不刪東西」。' -ForegroundColor Yellow
Write-Host '  它不會碰這個資料夾以外的任何檔案。' -ForegroundColor Yellow

# ───────────────────────── 1. 基本狀態 ─────────────────────────
Head '1. 這個資料夾現在的狀態'
if (-not (Test-Path -LiteralPath $target)) {
    Write-Host '  資料夾已經不存在了，沒事了。' -ForegroundColor Green
    Read-Host '  按 Enter 關閉'
    exit 0
}
$item = Get-Item -LiteralPath $target -Force
Write-Host "  建立時間 : $($item.CreationTime)"
Write-Host "  屬性     : $($item.Attributes)"
$files = @(Get-ChildItem -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue)
Write-Host "  裡面有   : $($files.Count) 個項目"
$ro = @($files | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReadOnly })
Write-Host "  唯讀檔   : $($ro.Count) 個"
if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    Write-Host '  ⚠ 這是連結點/OneDrive 佔位符，不是普通資料夾' -ForegroundColor Yellow
}

# ───────────────────────── 2. 擁有者與權限 ─────────────────────────
Head '2. 擁有者與權限（這一段請截圖）'
try {
    $acl = Get-Acl -LiteralPath $target
    Write-Host "  擁有者 : $($acl.Owner)"
    Write-Host "  目前登入的是 : $env:USERDOMAIN\$env:USERNAME"
    Write-Host ''
    Write-Host '  權限項目：'
    foreach ($a in $acl.Access) {
        $inh = if ($a.IsInherited) { '繼承' } else { '直接設定' }
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
    Write-Host ("  你是擁有者嗎 : " + $(if ($iAmOwner) { '是' } else { '不是' }))
    if ($denies.Count -gt 0) {
        Write-Host '  🔴 有「拒絕」規則，那優先於任何允許規則：' -ForegroundColor Red
        $denies | ForEach-Object { Write-Host "     $($_.IdentityReference)  $($_.FileSystemRights)" }
    }
    if ($mine.Count -eq 0 -and -not $iAmOwner) {
        Write-Host '  🔴 你既不是擁有者、權限清單裡也沒有你 —— 像是 ACL 問題' -ForegroundColor Red
    } elseif ($denies.Count -gt 0) {
        Write-Host '  🔴 有拒絕規則擋著 —— 像是 ACL 問題' -ForegroundColor Red
    } else {
        Write-Host '  ✅ 權限看起來是夠的 —— 那刪不掉多半是有東西鎖住，不是權限問題' -ForegroundColor Green
        Write-Host '     （這種情況重新開機後通常就刪得掉了）'
    }
} catch {
    Write-Host "  讀不到權限：$($_.Exception.Message)" -ForegroundColor Red
}

# ───────────────────────── 3. 誰鎖住它 ─────────────────────────
Head '3. 有沒有程式正在使用它'
$holders = @()
try {
    $procs = Get-Process -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        $path = $null
        try { $path = $p.Path } catch {}
        if ($path -and $path.StartsWith($target, [StringComparison]::OrdinalIgnoreCase)) {
            $holders += "$($p.ProcessName) (PID $($p.Id))  ← 執行檔在這個資料夾裡"
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
        $holders += "$($c.Name) (PID $($c.ProcessId))  ← 指令列提到這個資料夾"
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
            $holders += "檔案總管視窗，正開著：$loc"
        }
    }
} catch {}

if ($holders.Count -gt 0) {
    Write-Host '  🔴 找到正在使用這個資料夾的東西：' -ForegroundColor Red
    $holders | Select-Object -Unique | ForEach-Object { Write-Host "     $_" }
    Write-Host ''
    if ($script:explorerWins.Count -gt 0) {
        Write-Host '  ⭐ 你有檔案總管視窗正開著這個資料夾 —— 這就是最常見的原因。' -ForegroundColor Yellow
        Write-Host '     把那個視窗關掉（或切到別的資料夾）再刪一次，通常就好了。' -ForegroundColor Yellow
    } else {
        Write-Host '  → 先把這些關掉（或直接重新開機）再刪，多半就好了。' -ForegroundColor Yellow
    }
} else {
    Write-Host '  ✅ 沒有找到明顯鎖住它的程式' -ForegroundColor Green
    Write-Host '     （OneDrive、防毒在背景抓著檔案時查不出來；'
    Write-Host '      另外：如果你「點進去過」這個資料夾，檔案總管可能還記著它，'
    Write-Host '      先切到別的資料夾或關掉視窗再試）'
}

# ───────────────────────── 4. 建議 ─────────────────────────
Head '4. 建議的處理順序'
Write-Host '  照這個順序試，先試最安全的：'
Write-Host ''
Write-Host '   (1) ⭐ 關掉「檔案總管裡開著這個資料夾的視窗」，以及所有這個工具的'
Write-Host '       黑色視窗，然後再刪一次。'
Write-Host '       （實際案例中，這一步就解決了 —— 只是資料夾被自己開著）'
Write-Host '   (2) 還是不行 → 重新開機，開機後第一件事就是刪它。'
Write-Host '       ⭐ 這步同時也是診斷：重開機後刪得掉 = 剛才是被程式鎖住，'
Write-Host '          不是權限問題。'
Write-Host '   (3) 還是不行 → 用下面的「安全移除」試一次。'
Write-Host '   (4) 都不行 → 把上面第 2 段截圖，連同這個畫面一起回報。'
Write-Host ''
# 🔴 不要斷言「這個資料夾在 OneDrive 裡面」。那是開發這台電腦的情況，
#    同事的資料夾可能在 D 槽、隨身碟或網路磁碟，講錯會讓人以為工具在亂講。
if ($Target -like '*OneDrive*') {
    Write-Host '  ⚠ 網路上會叫你用 takeown / icacls 改權限 —— 這個資料夾在 OneDrive'  -ForegroundColor Yellow
    Write-Host '    裡面，那樣做有機會影響到同步的其他檔案，所以這支不做。'          -ForegroundColor Yellow
} else {
    Write-Host '  ⚠ 網路上會叫你用 takeown / icacls 改權限 —— 那會改動整個資料夾的'  -ForegroundColor Yellow
    Write-Host '    擁有者與權限，風險比它解決的問題大，所以這支不做。'              -ForegroundColor Yellow
}

# ───────────────────────── 5. 安全移除 ─────────────────────────
Head '5. 要不要現在試「安全移除」？'
Write-Host '  它會做這三件事，全部只限這個資料夾：'
Write-Host '    a. 把裡面的「唯讀」屬性拿掉'
Write-Host '    b. 先把資料夾改名搬到暫存區（改名成功 = 沒有權限問題）'
Write-Host '    c. 逐個檔案刪除，刪不掉的會列出來給你看'
Write-Host ''
$ans = Read-Host '  要試嗎？輸入 Y 然後按 Enter（直接按 Enter 就是不要）'
if ($ans -notmatch '^[Yy]') {
    Write-Host ''
    Write-Host '  沒有動任何東西。' -ForegroundColor Green
    Read-Host '  按 Enter 關閉'
    exit 0
}

Head '正在處理'
if ($script:explorerWins.Count -gt 0) {
    Write-Host "  0. 先關掉 $($script:explorerWins.Count) 個開著這個資料夾的檔案總管視窗…"
    foreach ($w in $script:explorerWins) { try { $w.Quit() } catch {} }
    Start-Sleep -Milliseconds 1200
    Write-Host '     關好了'
}
Write-Host '  a. 清除唯讀屬性…'
$cleared = 0
foreach ($f in $files) {
    if ($f.Attributes -band [IO.FileAttributes]::ReadOnly) {
        try { $f.Attributes = $f.Attributes -bxor [IO.FileAttributes]::ReadOnly; $cleared++ } catch {}
    }
}
Write-Host "     清掉 $cleared 個"

Write-Host '  b. 嘗試改名搬到暫存區…'
# 🔴 暫存區必須跟目標同一個磁碟，不能用 %TEMP%。
#    跨磁碟的 Move-Item 是「逐檔複製再刪除」，中途卡住會變成
#    「一半的檔已經被搬走，卻回報失敗」，比不動更糟。
#    同磁碟的 Move-Item 是單純改名：要嘛整個成功、要嘛完全不動。
#    （2026-09-10：uninstall_gui.py 先修好，這支漏了，是同一個病。）
$staged = Join-Path (Split-Path -Parent $target) ("_gs_delete_" + [Guid]::NewGuid().ToString('N').Substring(0, 8))
$moved = $false
try {
    Move-Item -LiteralPath $target -Destination $staged -ErrorAction Stop
    $moved = $true
    Write-Host '     ✅ 改名成功 —— 原本的資料夾名稱已經不見了（它暫時改名成 _gs_delete_…，接著逐個刪除）' -ForegroundColor Green
    Write-Host '        （代表不是權限問題，只是有東西鎖住內容）'
} catch {
    Write-Host "     ✗ 搬不動：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host '        代表還有程式抓著這個資料夾（不是權限問題）。' -ForegroundColor Yellow
    Write-Host ''
    # 🔴 這裡絕對不能往下走去逐檔刪除。
    #    舊版會在改名失敗後照樣刪光裡面所有檔案（含手冊和解除安裝程式），
    #    結果是「資料夾仍然刪不掉，但東西全沒了」，比不動更糟。
    Write-Host '  為了安全起見，沒有刪除任何檔案。' -ForegroundColor Green
    Write-Host '  請照下面做：' -ForegroundColor Yellow
    Write-Host '    1. 關掉所有檔案總管視窗，以及這個工具的所有黑色視窗'
    Write-Host '    2. 重新開機，開機後第一件事就是刪這個資料夾'
    Write-Host '    3. 還是不行，把上面第 2 段和第 3 段截圖回報'
    Write-Host ''
    Read-Host '  按 Enter 關閉'
    exit 0
}

Write-Host '  c. 逐個刪除…'
$failed = @()
Get-ChildItem -LiteralPath $staged -Recurse -Force -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | ForEach-Object {
        try { Remove-Item -LiteralPath $_.FullName -Force -Recurse -ErrorAction Stop }
        catch { $failed += "$($_.FullName)" }
    }
try { Remove-Item -LiteralPath $staged -Force -Recurse -ErrorAction Stop } catch { $failed += $staged }

Head '結果'
if ($failed.Count -eq 0) {
    Write-Host '  ✅ 全部刪乾淨了。' -ForegroundColor Green
} elseif ($moved) {
    Write-Host '  ✅ 原本的資料夾已經不見了（你的目的達成了）。' -ForegroundColor Green
    Write-Host "  ⚠ 但有 $($failed.Count) 個檔案還刪不掉，留在這個暫存資料夾裡：" -ForegroundColor Yellow
    Write-Host "     $staged"
    Write-Host '     它不會自己消失：重新開機後，直接在檔案總管把這個資料夾刪掉就好。'
} else {
    Write-Host "  ✗ 有 $($failed.Count) 個項目刪不掉：" -ForegroundColor Red
    $failed | Select-Object -First 12 | ForEach-Object { Write-Host "     $_" }
    Write-Host ''
    Write-Host '  請重新開機後再跑一次這支；還是不行就把畫面截圖回報。' -ForegroundColor Yellow
}
Write-Host ''
Read-Host '  按 Enter 關閉'
