export enum PreflightCalibrationMagnetometer {
	PREFLIGHT_CALIBRATION_MAGNETOMETER_NONE = 0, // No action.
	PREFLIGHT_CALIBRATION_MAGNETOMETER_START = 1, // Start magnetometer calibration.
	PREFLIGHT_CALIBRATION_MAGNETOMETER_FORCE_SAVE = 76, // Force-accept the existing compass calibration as valid without re-running it. Useful after a parameter reload that cleared calibration validity flags.
	PREFLIGHT_CALIBRATION_MAGNETOMETER_ENUM_END = 77, // 
}