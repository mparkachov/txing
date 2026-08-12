export enum MavSysStatusSensorExtended {
	MAV_SYS_STATUS_RECOVERY_SYSTEM = 1, // 0x01 Recovery system (parachute, balloon, retracts etc)
	MAV_SYS_STATUS_SENSOR_LEAK = 2, // 0x02 Leak detection
	MAV_SYS_STATUS_SENSOR_3D_GYRO3 = 4, // 0x04 3rd 3D gyro
	MAV_SYS_STATUS_SENSOR_3D_ACCEL3 = 8, // 0x08 3rd 3D accelerometer
	MAV_SYS_STATUS_SENSOR_3D_GYRO4 = 16, // 0x10 4th 3D gyro
	MAV_SYS_STATUS_SENSOR_3D_ACCEL4 = 32, // 0x20 4th 3D accelerometer
	MAV_SYS_STATUS_SENSOR_EXTENDED_ENUM_END = 33, // 
}