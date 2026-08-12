export enum NavTakeoffFlags {
	NAV_TAKEOFF_FLAGS_HORIZONTAL_POSITION_NOT_REQUIRED = 1, // Accept the command even if the autopilot does not have control over its horizontal position (note that it might not have altitude control either).
	NAV_TAKEOFF_FLAGS_ENUM_END = 2, // 
}