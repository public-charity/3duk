"""Fail closed on incomplete heightmap rendering resources, independently of Unreal imports."""


def require_heightmaps(report):
    if (report.get("error") or report.get("ready") is not True
            or report.get("missing_heightmaps") != 0):
        raise RuntimeError("landscape heightmaps are not ready: " + str(report))
    components, textures = report.get("components"), report.get("textures")
    if not isinstance(components, int) or components < 0 or not isinstance(textures, list):
        raise RuntimeError("incomplete heightmap readiness report")
    if (components > 0) != bool(textures):
        raise RuntimeError("landscape component/texture coverage mismatch")
    for row in textures:
        if (row.get("ready") is not True or row.get("fully_streamed") is not True
                or not isinstance(row.get("mips"), int) or row["mips"] < 1
                or row.get("resident_after") != row["mips"]):
            raise RuntimeError("heightmap mip residency mismatch: " + str(row))
    return report
