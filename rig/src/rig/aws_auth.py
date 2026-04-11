from aws import auth as _shared_auth
import sys as _sys

_sys.modules[__name__] = _shared_auth
