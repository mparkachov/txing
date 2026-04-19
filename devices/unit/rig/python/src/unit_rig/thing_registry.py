from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

LOGGER = logging.getLogger("rig.thing_registry")


class ThingGroupNotFoundError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class DeviceRegistration:
    device_id: str
    thing_name: str
    town_name: str
    rig_name: str
    device_type: str
    device_name: str
    ble_device_id: str | None = None
    version: int | None = None


def normalize_registry_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


class AwsThingRegistryClient:
    def __init__(self, client: Any) -> None:
        self._client = client

    def list_rig_things(self, rig_name: str) -> list[DeviceRegistration]:
        try:
            self._client.describe_thing_group(thingGroupName=rig_name)
        except Exception as exc:
            error_code = (
                getattr(exc, "response", {})
                .get("Error", {})
                .get("Code")
            )
            if error_code in {"ResourceNotFoundException", "ResourceNotFound"}:
                raise ThingGroupNotFoundError(
                    f"Dynamic thing group {rig_name!r} was not found"
                ) from exc
            raise

        next_token: str | None = None
        thing_names: list[str] = []
        while True:
            request: dict[str, Any] = {
                "thingGroupName": rig_name,
                "maxResults": 100,
            }
            if next_token:
                request["nextToken"] = next_token
            response = self._client.list_things_in_thing_group(**request)
            for item in response.get("things", []):
                thing_name = normalize_registry_text(item)
                if thing_name:
                    thing_names.append(thing_name)
            next_token = normalize_registry_text(response.get("nextToken"))
            if not next_token:
                break

        registrations: list[DeviceRegistration] = []
        for thing_name in sorted(set(thing_names)):
            try:
                registration = self.describe_thing(thing_name)
            except RuntimeError as exc:
                LOGGER.warning(
                    "Skipping thing=%s from dynamic group=%s: %s",
                    thing_name,
                    rig_name,
                    exc,
                )
                continue
            if registration.rig_name != rig_name:
                LOGGER.warning(
                    "Skipping thing=%s from dynamic group=%s because attributes.rig=%s",
                    thing_name,
                    rig_name,
                    registration.rig_name,
                )
                continue
            registrations.append(registration)
        return registrations

    def describe_thing(self, thing_name: str) -> DeviceRegistration:
        response = self._client.describe_thing(thingName=thing_name)
        attributes = response.get("attributes") or {}
        town_name = normalize_registry_text(attributes.get("town"))
        rig_name = normalize_registry_text(attributes.get("rig"))
        device_type = normalize_registry_text(attributes.get("deviceType"))
        device_name = normalize_registry_text(attributes.get("deviceName"))
        if town_name is None:
            raise RuntimeError(
                f"Thing {thing_name!r} is missing required IoT registry attribute 'town'"
            )
        if rig_name is None:
            raise RuntimeError(
                f"Thing {thing_name!r} is missing required IoT registry attribute 'rig'"
            )
        if device_type is None:
            raise RuntimeError(
                f"Thing {thing_name!r} is missing required IoT registry attribute 'deviceType'"
            )
        if device_name is None:
            raise RuntimeError(
                f"Thing {thing_name!r} is missing required IoT registry attribute 'deviceName'"
            )
        return DeviceRegistration(
            device_id=thing_name,
            thing_name=thing_name,
            town_name=town_name,
            rig_name=rig_name,
            device_type=device_type,
            device_name=device_name,
            ble_device_id=normalize_registry_text(attributes.get("bleDeviceId")),
            version=response.get("version"),
        )

    def update_ble_device_id(
        self,
        thing_name: str,
        *,
        ble_device_id: str | None,
        expected_version: int | None = None,
    ) -> DeviceRegistration:
        attributes: dict[str, str] = {}
        if ble_device_id is not None:
            attributes["bleDeviceId"] = ble_device_id

        request: dict[str, Any] = {
            "thingName": thing_name,
            "attributePayload": {
                "attributes": attributes,
                "merge": True,
            },
        }
        if expected_version is not None:
            request["expectedVersion"] = expected_version
        self._client.update_thing(**request)
        return self.describe_thing(thing_name)

    def assign_device(
        self,
        device_id: str,
        *,
        town_name: str,
        rig_name: str,
        expected_version: int | None = None,
    ) -> DeviceRegistration:
        request: dict[str, Any] = {
            "thingName": device_id,
            "attributePayload": {
                "attributes": {
                    "town": town_name,
                    "rig": rig_name,
                },
                "merge": True,
            },
        }
        if expected_version is not None:
            request["expectedVersion"] = expected_version
        self._client.update_thing(**request)
        return self.describe_thing(device_id)


ThingRegistration = DeviceRegistration
