export enum PreflightCalibrationAccelerometer {
	PREFLIGHT_CALIBRATION_ACCELEROMETER_NONE = 0, // No action.
	PREFLIGHT_CALIBRATION_ACCELEROMETER_FULL = 1, // Full 6-position accelerometer calibration.
	PREFLIGHT_CALIBRATION_ACCELEROMETER_TRIM = 2, // Board level (trim) calibration.
	PREFLIGHT_CALIBRATION_ACCELEROMETER_TEMPERATURE = 3, // Accelerometer temperature calibration.
	PREFLIGHT_CALIBRATION_ACCELEROMETER_SIMPLE = 4, // Simple accelerometer calibration.
	PREFLIGHT_CALIBRATION_ACCELEROMETER_FORCE_SAVE = 76, // Force-accept the existing accelerometer calibration as valid without re-running it. Useful after a parameter reload that cleared calibration validity flags.
	PREFLIGHT_CALIBRATION_ACCELEROMETER_ENUM_END = 77, // 
}