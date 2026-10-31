# 운항 도우미 - 비행준비 자료 자동 업로드 (이 PC → 구글 Apps Script 서버)
# - 개인 AI 비서 봇이 내보낸 공항별 요약 폴더(FP_DIR)를 읽기만 하고, 공항별 '중요' 항목만 서버로 보냄
# - 바뀐 공항만 보냄(파일 내용 비교). 목록에서 빠진 공항은 서버에서도 지움
# - 설정: config\fpdata.local.env (GitHub 에 올라가지 않음)  FP_DIR= / FP_URL= / FP_KEY=
# - 처음 설정: 비행준비_서버설정.bat (키 만들기 → 서버 주소 넣기 → 30분마다 자동 실행 등록)
param([switch]$Setup, [switch]$Force)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Base = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Sep = [IO.Path]::DirectorySeparatorChar
$Conf = [IO.Path]::Combine($Base, "config", "fpdata.local.env")
$PrivDir = Join-Path $Base "private"
if (-not (Test-Path $PrivDir)) { New-Item -ItemType Directory -Path $PrivDir | Out-Null }
$StateFile = Join-Path $PrivDir "fp_sync_state.json"
$LogFile = Join-Path $PrivDir "fp_sync.log"
$Utf8 = New-Object Text.UTF8Encoding($false)

function Log($m) { $l = (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + "  " + $m; Write-Host $l; try { [IO.File]::AppendAllText($LogFile, $l + "`r`n", $Utf8) } catch { } }
function ReadConf { $c = @{}; if (Test-Path -LiteralPath $Conf) { foreach ($ln in [IO.File]::ReadAllLines($Conf)) { if ($ln -match '^\s*([A-Z_]+)\s*=\s*"?(.*?)"?\s*$') { $c[$Matches[1]] = $Matches[2] } } }; return $c }
function WriteConf($c) { $lines = @("# 비행준비 설정 (이 PC 전용, GitHub 에 올라가지 않음)"); foreach ($k in @("FP_DIR", "FP_URL", "FP_KEY")) { if ($c[$k]) { $lines += "$k=$($c[$k])" } }; [IO.File]::WriteAllLines($Conf, $lines, $Utf8) }
# 봇 안내대로: 한 번에 읽고 바로 닫기, 없거나 깨졌으면 1초 뒤 다시
function ReadJson($p) { for ($i = 0; $i -lt 3; $i++) { try { return ([IO.File]::ReadAllText($p, $Utf8) | ConvertFrom-Json) } catch { Start-Sleep -Seconds 1 } }; return $null }
# 근거 규정 번호 표기(FCRM 1.7.6 등)는 '관련규정'으로 바꿔서 올림 (앱에서도 한 번 더 바꿈)
function NoRef([string]$t) {
  $t = $t -replace 'FCRM(?:\s*(?:Ch(?:apter)?\.?|Part|PT\.?)?\s*\d+(?:[.\-]\d+)*[A-Za-z]?)?(?:\s*(?:항|조|호)(?=[\s에의을를,.)]|$))?', '관련규정'
  $t = $t -replace '관련규정\s*규정', '관련규정'
  return ($t -replace '관련규정(?:\s*(?:[,·/]|및|와|과)\s*관련규정)+', '관련규정')
}
function Sha($p) { $s = [Security.Cryptography.SHA256]::Create(); try { return [BitConverter]::ToString($s.ComputeHash([IO.File]::ReadAllBytes($p))).Replace("-", "") } finally { $s.Dispose() } }

$C = ReadConf
if ($Setup) {
  if (-not $C["FP_KEY"]) {
    $b = New-Object byte[] 24; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    $C["FP_KEY"] = [Convert]::ToBase64String($b).Replace("+", "A").Replace("/", "B").Replace("=", "")
    WriteConf $C
  }
  try { Set-Clipboard -Value $C["FP_KEY"] } catch { }
  Write-Host ""
  Write-Host "  [1] 업로드 비밀키를 클립보드에 복사했습니다." -ForegroundColor Green
  Write-Host "      Apps Script → 프로젝트 설정 → 스크립트 속성 → 이름 UPLOAD_KEY, 값에 붙여넣기(Ctrl+V)"
  Write-Host "      (키는 이 PC 의 config\fpdata.local.env 에만 저장됩니다. 채팅·메일로 보내지 마세요)"
  Write-Host ""
  $u = Read-Host "  [2] 배포한 웹 앱 주소를 붙여넣고 Enter (이미 넣었으면 그냥 Enter)"
  if ($u -match '^https://script\.google\.com/macros/s/[\w-]+/exec$') { $C["FP_URL"] = $u; WriteConf $C; Write-Host "      저장했습니다." -ForegroundColor Green }
  elseif ($u) { Write-Host "      주소 모양이 다릅니다 (https://script.google.com/macros/s/…/exec). 다시 실행해 주세요." -ForegroundColor Red; exit 1 }
  $Force = $true
}
if (-not $C["FP_DIR"] -or -not $C["FP_URL"] -or -not $C["FP_KEY"]) { Log "설정이 덜 됐습니다 (FP_DIR / FP_URL / FP_KEY). 비행준비_서버설정.bat 을 실행하세요."; exit 1 }

$Dir = $C["FP_DIR"].TrimEnd("\", "/")
$idx = ReadJson (Join-Path $Dir "index.json")
if ($null -eq $idx) { Log "자료 목록(index.json)을 읽지 못했습니다: 폴더 확인"; exit 1 }
$state = @{}
if ((Test-Path -LiteralPath $StateFile) -and -not $Force) { try { $o = [IO.File]::ReadAllText($StateFile, $Utf8) | ConvertFrom-Json; foreach ($p in $o.PSObject.Properties) { $state[$p.Name] = $p.Value } } catch { } }

$now = @{}; $send = @()
foreach ($a in @($idx.airports)) {
  if (-not $a.icao -or -not $a.file) { continue }
  $f = [IO.Path]::GetFullPath([IO.Path]::Combine($Dir, ($a.file -replace "/", $Sep)))
  if (-not $f.StartsWith($Dir + $Sep, [StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $f)) { continue }
  $key = "$($a.company)|$($a.icao)"; $h = Sha $f; $now[$key] = $h
  if ($state[$key] -eq $h) { continue }
  $d = ReadJson $f; if ($null -eq $d) { Log "읽기 실패: $($a.icao)"; $now.Remove($key); continue }
  $pick = { param($role) @(@($d.items) | Where-Object { $_.role -eq $role -and [int]$_.priority -eq 1 } | Sort-Object { [int]$_.order } | ForEach-Object { [ordered]@{ text = (NoRef ([string]$_.text)); aircraft = @(@($_.aircraft) | Where-Object { $_ }); order = [int]$_.order; hazard = [bool]$_.hazard } }) }
  $chg = { param($role) @(@($d.changes) | Where-Object { $_ -and ($_.role -eq $role -or $_.role -eq "general" -or -not $_.role) } | ForEach-Object { [ordered]@{ type = [string]$_.type; text = (NoRef ([string]$_.text)) } }) }
  $send += [ordered]@{ company = [string]$d.company; icao = [string]$d.icao; iata = [string]$d.iata; eff_date = [string]$d.eff_date; date_label = [string]$d.date_label; version = [string]$d.version
    dep = @(& $pick "dep"); arr = @(& $pick "arr"); chg_dep = @(& $chg "dep"); chg_arr = @(& $chg "arr") }   # @(): 항목 1개여도 배열로 (PowerShell 은 1개면 배열을 풀어 버림)
}
$remove = @($state.Keys | Where-Object { -not $now.ContainsKey($_) } | ForEach-Object { $x = $_.Split("|"); [ordered]@{ company = $x[0]; icao = $x[1] } })
if (-not $send.Count -and -not $remove.Count) { Log "변경 없음 (공항 $($now.Count)곳)"; exit 0 }

function Post($airports, $rm) {
  $body = [ordered]@{ key = $C["FP_KEY"]; airports = @(@($airports) | Where-Object { $_ }); remove = @(@($rm) | Where-Object { $_ }); updated = [string]$idx.updated } | ConvertTo-Json -Depth 8 -Compress
  $r = Invoke-RestMethod -Method Post -Uri $C["FP_URL"] -Body ($Utf8.GetBytes($body)) -ContentType "application/json; charset=utf-8" -TimeoutSec 120
  if (-not $r.ok) { throw ("서버 응답: " + $r.err + " " + $r.msg) }
  return $r
}
try {
  for ($i = 0; $i -lt [Math]::Max($send.Count, 1); $i += 20) {
    $part = @(); if ($send.Count) { $part = $send[$i..([Math]::Min($i + 19, $send.Count - 1))] }
    $r = Post $part $(if ($i -eq 0) { $remove } else { @() })
  }
  [IO.File]::WriteAllText($StateFile, ($now | ConvertTo-Json -Compress), $Utf8)
  Log "업로드 완료: 보냄 $($send.Count)곳, 지움 $($remove.Count)곳, 서버 전체 $($r.total)곳"
} catch {
  Log ("업로드 실패: " + $_.Exception.Message + " (다음 실행 때 다시 시도)")
  exit 1
}
