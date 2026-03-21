# verify_index.ps1
# Verifies verses_index.json + keyword_index.json and prints key checks.

Set-Location "C:\kjv_project"

Write-Host "=== Current folder ==="
Get-Location

Write-Host "`n=== Check required files ==="
$files = @("verses_index.json", "keyword_index.json", "stats.json")
foreach ($f in $files) {
    if (Test-Path $f) {
        $info = Get-Item $f
        Write-Host ("OK: {0} ({1} KB)" -f $f, [math]::Round($info.Length / 1KB, 2))
    } else {
        Write-Host ("MISSING: {0}" -f $f) -ForegroundColor Red
    }
}

Write-Host "`n=== Step A: show first 5 verse_id lines ==="
Select-String -Path ".\verses_index.json" -Pattern '"verse_id":' -First 5 | ForEach-Object {
    $_.Line
}

Write-Host "`n=== Check: find John 3:16 by reference ==="
$johnRef = Select-String -Path ".\verses_index.json" -Pattern '"reference": "John 3:16"' -First 1
if ($johnRef) {
    Write-Host "FOUND John 3:16 reference ✅"
    $johnRef.Line
} else {
    Write-Host "NOT FOUND John 3:16 reference ❌" -ForegroundColor Yellow
}

Write-Host "`n=== Check: find JOHN_3_16 by verse_id ==="
$johnId = Select-String -Path ".\verses_index.json" -Pattern '"verse_id": "JOHN_3_16"' -First 1
if ($johnId) {
    Write-Host "FOUND JOHN_3_16 ✅"
    $johnId.Line
} else {
    Write-Host "NOT FOUND JOHN_3_16 ❌ (ID may be different format)" -ForegroundColor Yellow
}

Write-Host "`n=== Bonus: check keyword_index contains 'begotten' ==="
$beg = Select-String -Path ".\keyword_index.json" -Pattern '"begotten"' -First 1
if ($beg) {
    Write-Host "FOUND keyword 'begotten' ✅"
    $beg.Line
} else {
    Write-Host "NOT FOUND keyword 'begotten' ❌" -ForegroundColor Yellow
}

Write-Host "`n=== Done ==="
