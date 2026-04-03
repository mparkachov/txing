from txing_aws import mqtt as _shared_mqtt
import sys as _sys

_sys.modules[__name__] = _shared_mqtt
