SHARE_DOWNLOAD_POINTS = 1
NODE_POINTS_PER_MB = 0.1
POINTS_PER_EARNING_UNIT = 100


def share_download_points():
    return SHARE_DOWNLOAD_POINTS


def node_download_points(file_size_mb):
    return float(file_size_mb or 0) * NODE_POINTS_PER_MB


def points_to_earning_units(points):
    return float(points or 0) / POINTS_PER_EARNING_UNIT
