param(
    [string]$Source = "data/reference-library/control-boards/wood-closeup-shot-v3/reference-4x5-close.png",
    [string]$OutputDirectory = "data/reference-library/control-boards/wood-closeup-shot-v5"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$root = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $root $Source
$outputPath = Join-Path $root $OutputDirectory
New-Item -ItemType Directory -Path $outputPath -Force | Out-Null

$sourceImage = [System.Drawing.Image]::FromFile($sourcePath)

function Draw-Crop {
    param(
        [System.Drawing.Graphics]$Graphics,
        [System.Drawing.Rectangle]$Destination,
        [System.Drawing.Rectangle]$Crop
    )
    $Graphics.DrawImage(
        $sourceImage,
        $Destination,
        $Crop.X,
        $Crop.Y,
        $Crop.Width,
        $Crop.Height,
        [System.Drawing.GraphicsUnit]::Pixel
    )
}

function Draw-CropFit {
    param(
        [System.Drawing.Graphics]$Graphics,
        [System.Drawing.Rectangle]$Destination,
        [System.Drawing.Rectangle]$Crop
    )
    $scale = [Math]::Min($Destination.Width / $Crop.Width, $Destination.Height / $Crop.Height)
    $width = [int][Math]::Round($Crop.Width * $scale)
    $height = [int][Math]::Round($Crop.Height * $scale)
    $x = $Destination.X + [int][Math]::Floor(($Destination.Width - $width) / 2)
    $y = $Destination.Y + [int][Math]::Floor(($Destination.Height - $height) / 2)
    Draw-Crop $Graphics ([System.Drawing.Rectangle]::new($x, $y, $width, $height)) $Crop
}

function Draw-FeatheredCrop {
    param(
        [System.Drawing.Graphics]$Graphics,
        [System.Drawing.Rectangle]$Destination,
        [System.Drawing.Rectangle]$Crop,
        [int]$Feather = 30,
        [double]$Opacity = 1.0
    )
    $patch = New-Object System.Drawing.Bitmap $Destination.Width, $Destination.Height
    $patchGraphics = [System.Drawing.Graphics]::FromImage($patch)
    $patchGraphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    Draw-Crop $patchGraphics ([System.Drawing.Rectangle]::new(0, 0, $Destination.Width, $Destination.Height)) $Crop
    $patchGraphics.Dispose()
    for ($y = 0; $y -lt $patch.Height; $y++) {
        for ($x = 0; $x -lt $patch.Width; $x++) {
            $distance = [Math]::Min([Math]::Min($x, $patch.Width - 1 - $x), [Math]::Min($y, $patch.Height - 1 - $y))
            $t = [Math]::Min(1.0, $distance / [double]$Feather)
            $alpha = [int][Math]::Round(255 * $Opacity * $t * $t * (3 - 2 * $t))
            $color = $patch.GetPixel($x, $y)
            $patch.SetPixel($x, $y, [System.Drawing.Color]::FromArgb($alpha, $color.R, $color.G, $color.B))
        }
    }
    $Graphics.DrawImage($patch, $Destination)
    $patch.Dispose()
}

function New-EvidenceBoard {
    param(
        [string]$Filename,
        [bool]$IncludeReferenceCup
    )
    $bitmap = New-Object System.Drawing.Bitmap 1000, 1250
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $graphics.Clear([System.Drawing.Color]::FromArgb(232, 228, 222))

    # Two non-contiguous crops retain the real diffuse field without reproducing the scene layout.
    Draw-Crop $graphics ([System.Drawing.Rectangle]::new(0, 0, 500, 300)) ([System.Drawing.Rectangle]::new(0, 0, 255, 470))
    Draw-Crop $graphics ([System.Drawing.Rectangle]::new(512, 0, 488, 300)) ([System.Drawing.Rectangle]::new(650, 0, 353, 350))

    if ($IncludeReferenceCup) {
        # Entire primary assembly is one uninterrupted, aspect-correct geometry reference.
        # Tighten only the left margin so the mold-like stain is excluded without retouching the wood.
        Draw-CropFit $graphics ([System.Drawing.Rectangle]::new(0, 312, 550, 938)) ([System.Drawing.Rectangle]::new(240, 130, 440, 1000))
        # Blank the remaining stain-only margin; this does not touch the cup, straw or label evidence.
        $graphics.FillRectangle([System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(232, 228, 222)), 68, 900, 60, 350)
    } else {
        # Natural wood material evidence without the foreground reference container.
        Draw-Crop $graphics ([System.Drawing.Rectangle]::new(0, 312, 550, 938)) ([System.Drawing.Rectangle]::new(700, 900, 303, 354))
    }

    # Entire rear double-paper-cup assembly, including body, two rims, crema and curved text.
    Draw-CropFit $graphics ([System.Drawing.Rectangle]::new(562, 312, 438, 620)) ([System.Drawing.Rectangle]::new(555, 340, 340, 545))
    # Natural pale wood grain, color and soft contact-shadow evidence, avoiding the mold-like stain.
    Draw-Crop $graphics ([System.Drawing.Rectangle]::new(562, 944, 438, 306)) ([System.Drawing.Rectangle]::new(700, 920, 303, 334))

    $graphics.Dispose()
    $destination = Join-Path $outputPath $Filename
    $bitmap.Save($destination, [System.Drawing.Imaging.ImageFormat]::Png)
    $bitmap.Dispose()
    return $destination
}

try {
    New-EvidenceBoard "reference-cup-geometry-evidence.png" $true
    New-EvidenceBoard "source-cup-geometry-evidence.png" $false
}
finally {
    $sourceImage.Dispose()
}
