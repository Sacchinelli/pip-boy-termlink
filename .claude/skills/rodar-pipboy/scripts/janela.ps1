<#
    janela.ps1 — driver de janela Win32 para conferir o Pip-Boy TermLink rodando.

    Existe porque o Qt não oferece nada por fora para inspecionar a própria
    janela, e os exemplos genéricos de "rodar o app" assumem Linux com xvfb e
    tmux — que não se aplicam a um app Windows nativo. Sem isto, cada conferida
    recomeça do zero escrevendo o mesmo P/Invoke.

    Ações:
      estado   Diz se a janela existe, responde, e de qual site-packages o Qt
               veio (a checagem que prova o .venv — veja o SKILL.md).
      captura  Traz a janela para a frente e salva um PNG dela. Avisa se o
               quadro saiu praticamente vazio, que é falha de desenho disfarçada
               de sucesso: o processo vive, a janela existe, e não há nada nela.
      teclas   Foca a janela e envia uma sequência do SendKeys. Opcionalmente
               captura depois, que é o caso normal — mandar tecla sem olhar o
               resultado não prova nada.

    Exemplos:
      .\janela.ps1 -Acao estado
      .\janela.ps1 -Acao captura -Saida C:\tmp\janela.png
      .\janela.ps1 -Acao teclas -Teclas '^b' -Saida C:\tmp\caderno.png
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('estado', 'captura', 'teclas')]
    [string]$Acao,

    # Deixe vazio para localizar o app sozinho. Informe quando houver mais de
    # uma instância aberta e você souber qual quer.
    [int]$IdProcesso = 0,

    [string]$Saida,

    # Sintaxe do SendKeys: ^b = Ctrl+B, % = Alt, + = Shift, {ESC} {F12} {ENTER}.
    [string]$Teclas,

    # Folga entre focar/teclar e fotografar. O Qt anima a abertura de diálogo;
    # fotografar cedo demais pega a janela pela metade e parece defeito.
    [int]$EsperaMs = 900
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing, System.Windows.Forms

if (-not ('PipBoyWin' -as [type])) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class PipBoyWin {
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
}

function Get-AppPipBoy {
    param([int]$Id)

    if ($Id -gt 0) { return Get-Process -Id $Id }

    # Duas caras aparecem: o processo real do app e um intermediário sem
    # janela (o atalho do gerenciador do Python, ou o shell que lançou).
    # O que interessa é o que tem MainWindowHandle — os outros são passagem.
    $candidatos = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
        Where-Object { $_.CommandLine -match 'pip_boy' } |
        ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue } |
        Where-Object { $_.MainWindowHandle -ne 0 }

    if (-not $candidatos) {
        throw "Nenhuma janela do Pip-Boy encontrada. O app subiu? Veja o log de stdout/stderr do lançamento."
    }
    if ($candidatos.Count -gt 1) {
        Write-Warning "$($candidatos.Count) instâncias abertas; usando a primeira (PID $($candidatos[0].Id)). Use -IdProcesso para escolher."
    }
    return @($candidatos)[0]
}

function Show-Estado {
    param($Proc)

    Write-Output ("PID .......... {0}" -f $Proc.Id)
    Write-Output ("Janela ....... '{0}'" -f $Proc.MainWindowTitle)
    Write-Output ("Respondendo .. {0}" -f $Proc.Responding)
    Write-Output ("Memória ...... {0:N0} MB" -f ($Proc.WorkingSet64 / 1MB))

    # A prova de qual ambiente está em uso. NÃO olhe a python3XX.dll: um venv
    # compartilha o binário do interpretador base, então ela aponta para a
    # instalação global mesmo quando o venv está correto. O que muda é de onde
    # saem os pacotes, e o shiboken6 (o motor do PySide6) denuncia isso.
    $qt = $Proc.Modules |
        Where-Object { $_.ModuleName -match 'shiboken6' } |
        Select-Object -First 1 -ExpandProperty FileName
    if ($qt) {
        Write-Output ("Qt vem de .... {0}" -f $qt)
        if ($qt -notmatch '\.venv') {
            Write-Warning "O Qt NÃO veio do .venv. O app subiu por outro interpretador."
        }
    } else {
        Write-Warning "shiboken6 não carregado — a interface talvez ainda esteja subindo."
    }
}

function Measure-Quadro {
    # Dois números, duas falhas diferentes: "acesos" pega o quadro preto,
    # "cores" pega o preenchimento chapado — escuro, mas não preto. Os limiares
    # de alerta são folgados de propósito. O tema Fallout é quase monocromático
    # e quase toda a área da janela é fundo liso; apertar isso trocaria uma
    # falha rara por um alarme falso constante.
    param([System.Drawing.Bitmap]$Bitmap)

    $cores = New-Object 'System.Collections.Generic.HashSet[int]'
    $claros = 0
    $total = 0
    for ($y = 0; $y -lt $Bitmap.Height; $y += 8) {
        for ($x = 0; $x -lt $Bitmap.Width; $x += 8) {
            $p = $Bitmap.GetPixel($x, $y)
            [void]$cores.Add($p.ToArgb())
            if ($p.R + $p.G + $p.B -gt 40) { $claros++ }
            $total++
        }
    }
    return [pscustomobject]@{
        Cores = $cores.Count
        Pct   = if ($total) { 100 * $claros / $total } else { 0 }
    }
}

function Save-Janela {
    param($Proc, [string]$Caminho)

    if (-not $Caminho) { throw "-Saida é obrigatório para capturar." }

    $h = $Proc.MainWindowHandle
    if ([PipBoyWin]::IsIconic($h)) { [void][PipBoyWin]::ShowWindow($h, 9) }  # 9 = SW_RESTORE
    [void][PipBoyWin]::SetForegroundWindow($h)
    Start-Sleep -Milliseconds $EsperaMs

    $r = New-Object PipBoyWin+RECT
    [void][PipBoyWin]::GetWindowRect($h, [ref]$r)
    $w = $r.Right - $r.Left
    $alt = $r.Bottom - $r.Top
    if ($w -le 0 -or $alt -le 0) { throw "Retângulo inválido ($w x $alt) — a janela está minimizada ou fora da tela." }

    $pasta = Split-Path -Parent $Caminho
    if ($pasta -and -not (Test-Path $pasta)) { New-Item -ItemType Directory -Path $pasta -Force | Out-Null }

    $bmp = New-Object System.Drawing.Bitmap $w, $alt
    try {
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        try { $g.CopyFromScreen($r.Left, $r.Top, 0, 0, $bmp.Size) } finally { $g.Dispose() }

        # Amostragem em grade: um quadro preto ou de cor única significa que o
        # processo existe mas não desenhou. Isso passaria por sucesso em
        # qualquer verificação que só olhe o código de saída.
        $m = Measure-Quadro -Bitmap $bmp

        # Trazer a janela para a frente e fotografar em seguida às vezes pega o
        # quadro ANTES do Qt repintar. Não é hipótese: medindo a mesma janela
        # parada, a primeira foto deu 14 cores distintas e as seguintes deram
        # ~1050. Um alerta ali seria falso, e — pior — 14 passou raspando por
        # qualquer limiar razoável, então nem alertaria: entregaria uma foto
        # velha como se fosse o estado atual.
        #
        # Por isso, quando a medida sai degenerada a resposta é tirar outra
        # foto, não gritar. Se a segunda confirmar, aí sim é defeito de verdade.
        if ($m.Cores -lt 200) {
            Start-Sleep -Milliseconds 1200
            $g2 = [System.Drawing.Graphics]::FromImage($bmp)
            try { $g2.CopyFromScreen($r.Left, $r.Top, 0, 0, $bmp.Size) } finally { $g2.Dispose() }
            $m2 = Measure-Quadro -Bitmap $bmp
            Write-Verbose ("Refotografado: {0} -> {1} cores" -f $m.Cores, $m2.Cores)
            $m = $m2
        }

        $bmp.Save($Caminho, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally { $bmp.Dispose() }

    $pct = $m.Pct
    Write-Output ("Salvo ........ {0}" -f $Caminho)
    Write-Output ("Dimensões .... {0}x{1}" -f $w, $alt)
    Write-Output ("Conteúdo ..... {0} cores distintas, {1:N1}% de pixels acesos" -f $m.Cores, $pct)
    if ($m.Cores -lt 6 -or $pct -lt 2) {
        Write-Warning "Quadro praticamente vazio. O app não desenhou — trate como falha, não como sucesso."
    }
    Write-Output "Agora ABRA o PNG e olhe. A heurística acima pega o quadro morto, não o layout errado."
}

$proc = Get-AppPipBoy -Id $IdProcesso

switch ($Acao) {
    'estado' {
        Show-Estado -Proc $proc
    }
    'captura' {
        Show-Estado -Proc $proc
        Save-Janela -Proc $proc -Caminho $Saida
    }
    'teclas' {
        if (-not $Teclas) { throw "-Teclas é obrigatório para a ação 'teclas'." }
        [void][PipBoyWin]::SetForegroundWindow($proc.MainWindowHandle)
        Start-Sleep -Milliseconds 400
        [System.Windows.Forms.SendKeys]::SendWait($Teclas)
        Start-Sleep -Milliseconds $EsperaMs
        $proc.Refresh()
        Write-Output ("Enviado '{0}' | respondendo: {1}" -f $Teclas, $proc.Responding)
        if ($Saida) { Save-Janela -Proc $proc -Caminho $Saida }
    }
}
