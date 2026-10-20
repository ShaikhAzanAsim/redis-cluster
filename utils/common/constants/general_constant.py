# -------------------------
# ✅ Detection Keys
# -------------------------
CLASS_NAME = "class_name"
SHARED_PATH = "shared_path"
MODEL_ID = "model_id"
UNKNOWN = "unknown"
REGION = "region"
REGION_NAME = "region_name"
GLOBAL = "global"
ITEM_AT_CURRENT_REGION_NAME = "item_at_current_region_name"
IS_INTEREST_REGION_CROSSED = "is_interested_region_crossed"
BBOX = "bbox"
OTHER = "other"
OBB_XYWHR = "obb_xywhr"
OBB_POLYGON = "obb_polygon"
FOLLOWED_TO = "followed_to"
GROUP_ID = "group_id"
IS_GROUPED = "is_grouped"
MASK = "masks"
ORIG_IMG = "orig_img"
CENTRE = "centre"
DETECTION_ACTIVITIES = "activities"
DETECTION_PRIMARY_ACTIVITY = "primary_activity"
# -------------------------
# ✅ Keyword Argument Keys
# -------------------------
KWARG_TAG = "tag"
KWARG_SNAPSHOT_TAGS = "snapshot_tags"

# -------------------------
# ✅ Generic Tag Values
# -------------------------
ALL = "all"
DEFAULT_SNAPSHOT_TAGS = ["all"]
PERSON = "person"
TAG_WRONG_SHELF_ITEM = "wrong shelf item"
TAG_WRONG_PLACED = "wrong_placed"
TAG_CAR = "car"
TAG_BICYCLE = "bicycle"
DENT = "dent"
BUS = "bus"
TRUCK = "truck"
# -------------------------
# ✅ Detection Output Keys
# -------------------------
CONFIDENCE = "confidence"
CLASS_ID = "class_id"
TRACK_ID = "track_id"
# ISO 8601 UTC timestamp when the frame was read from the camera (for LiDAR / multi-sensor sync)
FRAME_CAPTURE_UTC = "frame_capture_utc"
# -------------------------
# ✅ Default / Fallback Values
# -------------------------
DEFAULT_CLASS_ID = -1
DEFAULT_CONFIDENCE = 0.0


# -------------------------
# ✅ Pose Estimation Keys
# -------------------------
KEYPOINTS = "keypoints"
SKELETON = "skeleton"
KEYPOINTS_CONFIDENCE = "keypoints_confidence"

# -------------------------
# ✅ Default Pose Values
# -------------------------
DEFAULT_KEYPOINTS: list = []
DEFAULT_KEYPOINTS_CONF: list = []


# -------------------------
# ✅ Pose + Activity Keys
# -------------------------
ACTIVITIES = "activities"
PRIMARY_ACTIVITY = "primary_activity"
POSE_FEATURE = "pose_feature"
POSE_FEATURE_LEG_EXTENSION_RATIO = "leg_extension_ratio"
POSE_FEATURE_SHOULDER_ANGLE = "shoulder_angle"
POSE_FEATURE_AVG_CONF = "avg_confidence"

# -------------------------
# ✅ Default Activity Values
# -------------------------
DEFAULT_ACTIVITY_NAME = "unknown"
DEFAULT_ACTIVITIES_DICT: dict = {}
DEFAULT_ACTIVITY_THRESHOLD = 0.3

# -------------------------
# ✅ Logging / Messages
# -------------------------
LOG_UNKNOWN_ACTIVITY = "Unknown activity"
CONFIRMING = "confirming..."


DEFAULT_MODEL_NAME = "default"


# -------------------------
# ✅ track ID
# -------------------------

DETECT_TRACK_ID = "track_id"
DEFAULT_TRACK_ID = "unknown"

# --------------------------------
# ✅ Distance Between detections
# --------------------------------

DISTANCE_BETWEEN_SCAN_ITEMS = "distance_scan_items"
FEATURES_SCAN_TRANSFORMER = "features_scan_transformer"
