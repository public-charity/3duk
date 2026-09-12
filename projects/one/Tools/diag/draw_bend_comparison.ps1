param([Parameter(Mandatory)][string]$DiagramRoot)
Add-Type -AssemblyName System.Drawing
$diagramData=Get-Content -LiteralPath "$DiagramRoot/comparison.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$diagramBitmap=[System.Drawing.Bitmap]::new(1400,800)
$diagramGraphics=[System.Drawing.Graphics]::FromImage($diagramBitmap)
$diagramGraphics.Clear([System.Drawing.Color]::White)
$diagramFont=[System.Drawing.Font]::new('Arial',15)
$diagramSmallFont=[System.Drawing.Font]::new('Arial',11)
$diagramBrushes=@{
 road=[System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(145,161,173))
 pavement=[System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(222,184,119))
}
try {
 $diagramGraphics.DrawString($diagramData.title,$diagramFont,[System.Drawing.Brushes]::Black,20,15)
 $diagramScale=[Math]::Min(640/$diagramData.extent_m[0],630/$diagramData.extent_m[1])
 for ($diagramColumn=0;$diagramColumn -lt 2;$diagramColumn++) {
  $diagramKey=if ($diagramColumn -eq 0) {'before'} else {'after'}
  $diagramLabel=if ($diagramColumn -eq 0) {'Before'} else {'Complete-document geometry candidate'}
  $diagramCenterX=350+700*$diagramColumn
  $diagramCenterY=420
  $diagramGraphics.DrawString($diagramLabel,$diagramFont,[System.Drawing.Brushes]::Black,[single](20+700*$diagramColumn),55)
  $diagramGraphics.SetClip([System.Drawing.RectangleF]::new([single](20+700*$diagramColumn),90,660,640))
  foreach ($diagramPolygon in $diagramData.$diagramKey) {
   $diagramPoints=[System.Drawing.PointF[]]@($diagramPolygon.points | ForEach-Object {
    [System.Drawing.PointF]::new([single]($diagramCenterX+$diagramScale*$_[0]),[single]($diagramCenterY-$diagramScale*$_[1]))
   })
   $diagramGraphics.FillPolygon($diagramBrushes[$diagramPolygon.kind],$diagramPoints)
  }
  foreach ($diagramNode in $diagramData.nodes) {
   $diagramGraphics.FillEllipse([System.Drawing.Brushes]::SteelBlue,[single]($diagramCenterX+$diagramScale*$diagramNode[0]-2),[single]($diagramCenterY-$diagramScale*$diagramNode[1]-2),4,4)
  }
  $diagramGraphics.ResetClip()
 }
 $diagramGraphics.DrawString('Grey: road | Tan: kerb / pavement | Blue: original control | Same scale | Terrain / inherited intersections require separate checks',$diagramSmallFont,[System.Drawing.Brushes]::Black,20,755)
 $diagramBitmap.Save([System.IO.Path]::GetFullPath("$DiagramRoot/comparison.png"),[System.Drawing.Imaging.ImageFormat]::Png)
} finally {
 $diagramGraphics.Dispose();$diagramBitmap.Dispose();$diagramFont.Dispose();$diagramSmallFont.Dispose()
 foreach ($diagramBrush in $diagramBrushes.Values) {$diagramBrush.Dispose()}
}
