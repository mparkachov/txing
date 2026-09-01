export enum GlobalPositionFlags {
	GLOBAL_POSITION_UNHEALTHY = 1, // Unhealthy sensor/estimator.
	GLOBAL_POSITION_PRIMARY = 2, // True if the data originates from or is consumed by the primary estimator.
	GLOBAL_POSITION_FLAGS_ENUM_END = 3, // 
}