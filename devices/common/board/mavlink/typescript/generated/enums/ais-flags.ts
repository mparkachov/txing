export enum AisFlags {
	AIS_FLAGS_POSITION_ACCURACY = 1, // 1 = High (Position accuracy less than or equal to 10m), 0 = Low (position accuracy greater than 10m).
	AIS_FLAGS_VALID_COG = 2, // The COG field contains valid data
	AIS_FLAGS_VALID_VELOCITY = 4, // The velocity field contains valid data
	AIS_FLAGS_HIGH_VELOCITY = 8, // 1 = Velocity over 52.5765m/s (102.2 knots)
	AIS_FLAGS_VALID_TURN_RATE = 16, // The turn_rate field contains valid data
	AIS_FLAGS_TURN_RATE_SIGN_ONLY = 32, // Only the sign of the returned turn_rate value is valid. The actual turn rate is either greater than 5deg/30s or less than -5deg/30s.
	AIS_FLAGS_VALID_DIMENSIONS = 64, // 
	AIS_FLAGS_LARGE_BOW_DIMENSION = 128, // Distance to bow is greater than or equal to 511m
	AIS_FLAGS_LARGE_STERN_DIMENSION = 256, // Distance to stern is greater than or equal to 511m
	AIS_FLAGS_LARGE_PORT_DIMENSION = 512, // Distance to port side is greater than or equal to 63m
	AIS_FLAGS_LARGE_STARBOARD_DIMENSION = 1024, // Distance to starboard side is greater than or equal to 63m
	AIS_FLAGS_VALID_CALLSIGN = 2048, // The callsign field contains valid data
	AIS_FLAGS_VALID_NAME = 4096, // The name field contains valid data
	AIS_FLAGS_ENUM_END = 4097, // 
}