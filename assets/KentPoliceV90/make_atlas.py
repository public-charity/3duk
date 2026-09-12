"""Deterministic 4K paint / surface atlas. No photographs or external artwork.

Each island has 16 px padding. Side geometry and graphics share the same
coordinates; lettering is independently oriented on the two sides.
"""
from pathlib import Path
import json
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT = Path(__file__).resolve().parent
SIZE = 4096
PAD = 16
# Pixel rectangles and physical projection ranges, with V measured from bottom.
ISLANDS = {
    'left': ([16, 16, 2040, 660], [-2.6, 2.6, .15, 1.8]),
    'right': ([2056, 16, 4080, 660], [-2.6, 2.6, .15, 1.8]),
    'top': ([16, 720, 3040, 1976], [-2.6, 2.6, -1.08, 1.08]),
    'front': ([16, 2072, 1992, 3656], [-1.08, 1.08, .12, 1.85]),
    'rear': ([2096, 2072, 4072, 3656], [-1.08, 1.08, .12, 1.85]),
}
WHITE = (219, 227, 229)
BLUE = (14, 74, 140)
YELLOW = (223, 240, 56)
GLASS = (28, 49, 59)
TRIM = (23, 31, 35)
RED = (209, 32, 43)
SILVER = (156, 176, 187)
# Packed channels: roughness, metalness, emission weight.
PAINT = (94, 32, 0)
GLAZING = (72, 38, 0)
DARK = (110, 12, 0)
BRIGHT = (68, 38, 75)
FONT = 'C:/Windows/Fonts/arialbd.ttf'
base = Image.new('RGB', (SIZE, SIZE), WHITE)
surface = Image.new('RGB', (SIZE, SIZE), PAINT)


class Island:
    def __init__(self, name):
        self.rect, self.domain = ISLANDS[name]
        x0, y0, x1, y1 = self.rect
        self.image = Image.new('RGB', (x1-x0, y1-y0), WHITE)
        self.pbr = Image.new('RGB', self.image.size, PAINT)
        self.d = ImageDraw.Draw(self.image)
        self.p = ImageDraw.Draw(self.pbr)

    def xy(self, p):
        a, b, c, d = self.domain
        return ((p[0]-a)/(b-a)*(self.image.width-1),
                (d-p[1])/(d-c)*(self.image.height-1))

    def poly(self, pts, color, packed=PAINT):
        pts = [self.xy(p) for p in pts]
        self.d.polygon(pts, fill=color)
        self.p.polygon(pts, fill=packed)

    def rounded(self, bounds, radius, color, packed=PAINT):
        a, b, c, d = bounds
        xy = (*self.xy((a, d)), *self.xy((c, b)))
        pixels = radius*self.image.width/(self.domain[1]-self.domain[0])
        self.d.rounded_rectangle(xy, pixels, fill=color)
        self.p.rounded_rectangle(xy, pixels, fill=packed)

    def line(self, pts, color, width=.004, packed=PAINT):
        px = max(1, round(width*self.image.width/(self.domain[1]-self.domain[0])))
        pts = [self.xy(p) for p in pts]
        self.d.line(pts, fill=color, width=px, joint='curve')
        self.p.line(pts, fill=packed, width=px, joint='curve')

    def text(self, p, text, height, color, angle=0):
        size = round(height*self.image.width/(self.domain[1]-self.domain[0]))
        font = ImageFont.truetype(FONT, size)
        box = font.getbbox(text)
        tile = Image.new('RGBA', (box[2]+8, box[3]-box[1]+8))
        ImageDraw.Draw(tile).text((4, 4-box[1]), text, font=font, fill=(*color, 255))
        if angle: tile = tile.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        x, y = self.xy(p)
        self.image.paste(tile, (round(x-tile.width/2), round(y-tile.height/2)), tile)

    def finish(self, name, flip=False):
        if flip:
            self.image = self.image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            self.pbr = self.pbr.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        # Dilated island boundary prevents white/dark bleed at mip levels.
        for target, img in [(base, self.image), (surface, self.pbr)]:
            padded = img.resize((img.width+2*PAD, img.height+2*PAD))
            x, y = self.rect[:2]
            target.paste(padded, (x-PAD, y-PAD))
            target.paste(img, (x, y))


for side in ('left', 'right'):
    a = Island(side)
    # Same six broad Battenburg columns on each side, with clean outer margins.
    for row in range(2):
        for col in range(9):
            x = -2.46 + col*.55
            z = .34 + row*.245
            lo=max(-2.30,x); hi=min(2.27,x+.55)
            a.poly([(lo,z),(hi,z),(hi,z+.245),(lo,z+.245)],
                   YELLOW if (col+row)%2 == 0 else BLUE)
    # One continuous black surround. Individual panes are flat graphics on the
    # same curved shell, so they cannot intersect or detach from it.
    a.poly([(-2.145,.966),(-1.682,1.369),(-1.51,1.395),(-.02,1.382),
            (.12,1.332),(.724,.969)], TRIM, GLAZING)
    panes = [
        [(-2.064,.993),(-1.663,1.337),(-1.449,1.356),(-1.395,.993)],
        [(-1.337,.993),(-1.389,1.359),(-.508,1.362),(-.508,.993)],
        [(-.453,.993),(-.453,1.360),(-.027,1.352),(.084,1.306),(.662,.993)],
    ]
    for p in panes: a.poly(p, GLASS, GLAZING)
    a.line([(-2.10,.962),(.716,.962)], SILVER, .007, (75,150,0))
    # Subtle printed shut lines replace the protruding black wire geometry.
    seam = (100, 125, 139)
    a.line([(-.476,.95),(-.476,.30),(.57,.30),(.64,.70),(.71,.94)], seam, .0028)
    a.line([(-1.365,.95),(-1.275,.75),(-1.07,.30),(-.492,.30)], seam, .0028)
    for x in (-1.19,-.27):
        a.rounded((x-.08,.862,x+.08,.882), .01, (124,149,157), (105,45,0))
    a.line([(-1.00,.268),(1.00,.268)], (136,157,163), .009)
    # Flush rear side lens; no raised tail-light tubes.
    a.rounded((-2.41,.753,-2.20,.868), .023, RED, BRIGHT)
    # Right-hand atlas reverses world X. Put lettering in after flipping so it
    # reads correctly from either side without altering geometry symmetry.
    if side == 'right':
        a.image = a.image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        a.pbr = a.pbr.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        a.d = ImageDraw.Draw(a.image); a.p = ImageDraw.Draw(a.pbr)
    sign = 1 if side == 'left' else -1
    center = sign*.14
    a.rounded((center-.30,.604,center+.30,.818), .035, WHITE)
    a.text((center,.736), 'KENT', .078, BLUE)
    a.text((center,.658), 'POLICE', .068, BLUE)
    a.finish(side)

a = Island('top')
# Windshield and rear glass are analytically symmetrical around Y=0.
a.poly([(.19,-.630),(.19,.630),(.776,.756),(.802,.720),(.802,-.720),(.776,-.756)], TRIM, GLAZING)
a.poly([(.224,-.613),(.224,.613),(.755,.721),(.773,.705),(.773,-.705),(.755,-.721)], GLASS, GLAZING)
a.poly([(-1.762,-.585),(-1.762,.585),(-2.177,.713),(-2.214,.674),(-2.214,-.674),(-2.177,-.713)], TRIM, GLAZING)
a.poly([(-1.797,-.564),(-1.797,.564),(-2.152,.677),(-2.176,.655),(-2.176,-.655),(-2.152,-.677)], GLASS, GLAZING)
for sign in (-1,1):
    a.line([(.90,sign*.713),(1.86,sign*.710),(2.28,sign*.678)], (158,177,181), .0025)
a.poly([(.895,-.705),(.895,.705),(2.30,.670),(2.30,-.670)], YELLOW)
a.text((1.62,0), 'POLICE', .275, BLUE, 90)
a.finish('top')

a = Island('front')
# These are texture features on the rounded nose, including broad lens areas.
a.rounded((-.477,.511,.477,.756), .070, (113,139,151), (83,145,0))
a.rounded((-.460,.526,.460,.741), .060, TRIM, DARK)
for i in range(-10,11): a.line([(i*.039,.55),(i*.039,.717)], (66,88,101), .010, (98,90,0))
a.line([(-.38,.556),(.38,.71)], (174,189,197), .012, (78,170,0))
a.rounded((-.056,.579,.056,.692), .055, (160,179,188), (77,158,0))
a.rounded((-.042,.591,.042,.680), .041, BLUE)
for side in (-1,1):
    pts = [(side*.520,.654),(side*.879,.679),(side*.871,.790),(side*.522,.763)]
    a.poly(pts, (89,116,130), (62,60,0))
    pts = [(side*.540,.669),(side*.858,.691),(side*.854,.772),(side*.540,.747)]
    a.poly(pts, GLASS, GLAZING)
    a.line([(side*.553,.701),(side*.831,.721)], (221,240,245), .025, BRIGHT)
    a.rounded((min(side*.23,side*.30),.603,max(side*.23,side*.30),.633), .009, BLUE, BRIGHT)
a.rounded((-.77,.284,.77,.375), .04, TRIM, DARK)
a.rounded((-.277,.398,.277,.490), .009, (240,240,230), PAINT)
a.text((0,.444), 'GN22 BWC', .067, TRIM)
a.finish('front')

a = Island('rear')
a.rounded((-.785,.647,.785,.895), .035, YELLOW)
# Explicitly mirrored chevrons, including the central V.
for s in (-1,1):
    for i in range(4):
        v=i*.21
        a.poly([(s*v,.667),(s*(v+.10),.667),(s*(v+.31),.876),(s*(v+.21),.876)], RED)
    lo,hi=sorted([s*.69,s*.872])
    a.rounded((lo,.726,hi,.887), .027, TRIM, GLAZING)
    lo,hi=sorted([s*.713,s*.852])
    a.rounded((lo,.747,hi,.867), .020, RED, BRIGHT)
    a.line([(s*.65,.319),(s*.79,.319)], RED, .018, BRIGHT)
a.rounded((-.286,.463,.286,.589), .022, (156,174,179))
a.rounded((-.262,.482,.262,.578), .012, YELLOW)
a.text((0,.53), 'GN22 BWC', .065, TRIM)
a.text((0,.945), 'POLICE', .082, BLUE)
a.rounded((-.75,.232,.75,.291), .025, TRIM, DARK)
a.finish('rear')

base.save(OUT/'T_V90_BaseColor.png')
surface.save(OUT/'T_V90_Surface.png')
(OUT/'atlas_layout.json').write_text(json.dumps({'size':SIZE,'padding':PAD,'islands':ISLANDS},indent=2))
print('V90_UV_ATLAS_OK')
