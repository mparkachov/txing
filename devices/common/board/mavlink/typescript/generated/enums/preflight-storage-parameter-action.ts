export enum PreflightStorageParameterAction {
	PARAM_READ_PERSISTENT = 0, // Read all parameters from persistent storage. Replaces values in volatile storage.
	PARAM_WRITE_PERSISTENT = 1, // Write all parameter values to persistent storage (flash/EEPROM)
	PARAM_RESET_FACTORY_DEFAULT = 2, // Reset parameters to default values (such as sensor calibration, safety settings, and so on). Note that a flight stack may choose not to reset some parameters at their own discretion (such as those that are locked or expected to persist for the vehicle lifetime).
	PARAM_RESET_SENSOR_DEFAULT = 3, // Reset only sensor calibration parameters to factory defaults (or firmware default if not available)
	PARAM_RESET_ALL_DEFAULT = 4, // Reset all parameters to default values.
	PREFLIGHT_STORAGE_PARAMETER_ACTION_ENUM_END = 5, // 
}