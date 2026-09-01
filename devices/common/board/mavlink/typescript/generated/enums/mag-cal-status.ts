export enum MagCalStatus {
	MAG_CAL_NOT_STARTED = 0, // 
	MAG_CAL_WAITING_TO_START = 1, // 
	MAG_CAL_RUNNING_STEP_ONE = 2, // 
	MAG_CAL_RUNNING_STEP_TWO = 3, // 
	MAG_CAL_SUCCESS = 4, // 
	MAG_CAL_FAILED = 5, // 
	MAG_CAL_FAILED_ORIENTATION = 6, // Compass calibration failed: the vehicle orientation is outside the required tolerance.
	MAG_CAL_FAILED_RADIUS = 7, // Compass calibration failed: the radius of the fitted sphere is unrealistically small or large.
	MAG_CAL_FAILED_OFFSETS = 8, // Compass calibration failed: offset magnitude too large.
	MAG_CAL_FAILED_DIAG_SCALING = 9, // Compass calibration failed: diagonal or off-diagonal scaling values out of valid range.
	MAG_CAL_FAILED_RESIDUALS_HIGH = 10, // Compass calibration failed: fitness (RMS residual) exceeds tolerance.
	MAG_CAL_STATUS_ENUM_END = 11, // 
}