"""Compare integer-post ground probes without confusing collision compression with raw height data.

UE GetHeightAtLocation(Editor) samples Chaos's separately quantized heightfield
and returns float centimetres. Require the same nearest 1/128 m height code AND
a 0.5 mm readback bound. PreviewLandscapeHeightsJson separately compares raw
uint16 landscape writes/restores exactly; these probes check the source terrain.
"""
import math


def compare_ground_posts(points,actual,column):
    if column not in (2,3) or not 1<=len(points)<=4096 or len(actual)!=len(points):
        raise ValueError('invalid native ground probe coverage')
    errors=[];mismatches=0
    for point,height in zip(points,actual):
        if len(point)!=4 or not all(math.isfinite(v) for v in point) or not math.isfinite(height):
            raise ValueError('nonfinite native ground probe')
        if any(abs(v-round(v))>1e-8 for v in point[:2]):raise ValueError('native ground probes require integer metre posts')
        expected=point[column]
        encoded=expected*128.+32768.
        if not 0<=encoded<=65535 or abs(encoded-round(encoded))>1e-7:raise ValueError('expected ground is not landscape encoded')
        mismatches+=round(height*128.+32768.)!=round(encoded)
        errors.append(abs(height-expected))
    maximum=max(errors)
    return dict(samples=len(points),max_error_m=maximum,encoded_mismatches=mismatches,
        probe_tolerance_m=.0005,ok=mismatches==0 and maximum<=.0005,
        measurement='Chaos Editor height probe; nearest landscape height code plus 0.5 mm readback bound')
