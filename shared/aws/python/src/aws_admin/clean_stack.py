import json
import logging
import time
import urllib.request

import boto3

from aws_admin.cfn import stack_is_deleting


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
s3 = None
iot = None
ssm = None


def _s3():
    global s3
    if s3 is None:
        s3 = boto3.client("s3")
    return s3


def _iot():
    global iot
    if iot is None:
        iot = boto3.client("iot")
    return iot


def _ssm():
    global ssm
    if ssm is None:
        ssm = boto3.client("ssm")
    return ssm


IOT_FLEET_INDEXING_PHYSICAL_ID = "txing-iot-fleet-indexing"
IOT_FLEET_INDEXING_CUSTOM_FIELDS = [
    "attributes.name",
    "attributes.kind",
    "attributes.townId",
    "attributes.rigId",
]
SSM_THROTTLE_ERROR_CODES = {
    "ThrottlingException",
    "ThrottledException",
    "TooManyUpdates",
    "TooManyRequestsException",
    "RequestLimitExceeded",
    "RateExceededException",
}
SSM_MAX_ATTEMPTS = 12
SSM_DELETE_BATCH_SIZE = 10
SSM_DELETE_BATCH_DELAY_SECONDS = 0.25


def _send_response(
    event,
    context,
    status,
    data=None,
    reason=None,
    physical_resource_id=None,
):
    body = json.dumps(
        {
            "Status": status,
            "Reason": reason or f"See CloudWatch log stream: {context.log_stream_name}",
            "PhysicalResourceId": physical_resource_id
            or event.get("PhysicalResourceId")
            or f"{event['StackId']}/{event['LogicalResourceId']}",
            "StackId": event["StackId"],
            "RequestId": event["RequestId"],
            "LogicalResourceId": event["LogicalResourceId"],
            "NoEcho": False,
            "Data": data or {},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        event["ResponseURL"],
        data=body,
        method="PUT",
        headers={
            "content-type": "",
            "content-length": str(len(body)),
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()


def _error_code(error):
    return getattr(error, "response", {}).get("Error", {}).get("Code")


def _is_ssm_throttle(error):
    code = _error_code(error)
    message = str(error).lower()
    return (
        code in SSM_THROTTLE_ERROR_CODES
        or "throttl" in message
        or "rate exceeded" in message
    )


def _ssm_call(description, operation, **kwargs):
    for attempt in range(SSM_MAX_ATTEMPTS):
        try:
            return operation(**kwargs)
        except Exception as error:
            if not _is_ssm_throttle(error) or attempt == SSM_MAX_ATTEMPTS - 1:
                raise
            delay = min(30.0, 1.0 * (2**attempt))
            LOGGER.warning(
                "SSM %s throttled; retrying attempt %s/%s in %.1fs: %s",
                description,
                attempt + 2,
                SSM_MAX_ATTEMPTS,
                delay,
                error,
            )
            time.sleep(delay)


def _ignore_missing_bucket(error):
    return _error_code(error) in {"NoSuchBucket", "404", "NotFound"}


def _delete_objects(bucket, objects):
    if not objects:
        return 0
    deleted = 0
    for offset in range(0, len(objects), 1000):
        chunk = objects[offset : offset + 1000]
        response = _s3().delete_objects(
            Bucket=bucket,
            Delete={"Objects": chunk, "Quiet": True},
        )
        errors = response.get("Errors", [])
        if errors:
            raise RuntimeError(f"Failed to delete objects from {bucket}: {errors}")
        deleted += len(chunk)
    return deleted


def _empty_bucket(bucket):
    deleted = 0
    try:
        paginator = _s3().get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket):
            versioned_objects = [
                {"Key": item["Key"], "VersionId": item["VersionId"]}
                for item in page.get("Versions", [])
            ]
            delete_markers = [
                {"Key": item["Key"], "VersionId": item["VersionId"]}
                for item in page.get("DeleteMarkers", [])
            ]
            deleted += _delete_objects(bucket, versioned_objects + delete_markers)

        object_paginator = _s3().get_paginator("list_objects_v2")
        for page in object_paginator.paginate(Bucket=bucket):
            objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            deleted += _delete_objects(bucket, objects)
    except Exception as error:
        if _ignore_missing_bucket(error):
            return {"deletedObjects": deleted, "missing": True}
        raise
    return {"deletedObjects": deleted, "missing": False}


def _fleet_indexing_configuration():
    return {
        "thingIndexingMode": "REGISTRY",
        "thingConnectivityIndexingMode": "STATUS",
        "customFields": [
            {"name": name, "type": "String"}
            for name in IOT_FLEET_INDEXING_CUSTOM_FIELDS
        ],
    }


def _fleet_indexing_matches(configuration):
    fields = {
        item.get("name"): item.get("type")
        for item in configuration.get("customFields", [])
    }
    return (
        configuration.get("thingIndexingMode") == "REGISTRY"
        and configuration.get("thingConnectivityIndexingMode") == "STATUS"
        and all(fields.get(name) == "String" for name in IOT_FLEET_INDEXING_CUSTOM_FIELDS)
    )


def _configure_iot_fleet_indexing():
    expected = _fleet_indexing_configuration()
    _iot().update_indexing_configuration(thingIndexingConfiguration=expected)
    deadline = time.monotonic() + 120
    while True:
        response = _iot().get_indexing_configuration()
        configuration = response.get("thingIndexingConfiguration", {})
        if _fleet_indexing_matches(configuration):
            return {
                "thingIndexingMode": configuration.get("thingIndexingMode"),
                "thingConnectivityIndexingMode": configuration.get(
                    "thingConnectivityIndexingMode"
                ),
                "customFields": ",".join(IOT_FLEET_INDEXING_CUSTOM_FIELDS),
            }
        if time.monotonic() >= deadline:
            raise TimeoutError("Timed out waiting for AWS IoT fleet indexing configuration")
        time.sleep(3)


def _as_string_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise TypeError(f"Expected list or comma-separated string, got {type(value).__name__}")


def _thing_type_properties(properties):
    return {
        "thingTypeDescription": properties.get("ThingTypeDescription", ""),
        "searchableAttributes": _as_string_list(properties.get("SearchableAttributes")),
    }


def _ensure_thing_type(properties):
    thing_type_name = properties["ThingTypeName"]
    thing_type_properties = _thing_type_properties(properties)
    try:
        _iot().create_thing_type(
            thingTypeName=thing_type_name,
            thingTypeProperties=thing_type_properties,
        )
        return "created"
    except Exception as error:
        if _error_code(error) != "ResourceAlreadyExistsException":
            raise

    description = _iot().describe_thing_type(thingTypeName=thing_type_name)
    metadata = description.get("thingTypeMetadata", {})
    if metadata.get("deprecated"):
        _iot().deprecate_thing_type(
            thingTypeName=thing_type_name,
            undoDeprecate=True,
        )
    current_properties = description.get("thingTypeProperties", {})
    if (
        current_properties.get("thingTypeDescription", "")
        == thing_type_properties["thingTypeDescription"]
        and sorted(current_properties.get("searchableAttributes", []))
        == sorted(thing_type_properties["searchableAttributes"])
    ):
        return "existing"
    _iot().update_thing_type(
        thingTypeName=thing_type_name,
        thingTypeProperties=thing_type_properties,
    )
    return "updated"


def _catalog_parameter_name(base_path, leaf_name):
    base = str(base_path).rstrip("/")
    leaf = str(leaf_name).strip("/")
    if not base.startswith("/txing/") and base != "/txing":
        raise ValueError(f"Type catalog path must be under /txing: {base_path!r}")
    if not leaf:
        raise ValueError("Type catalog leaf name must not be empty")
    return f"{base}/{leaf}"


def _catalog_existing_parameters(base_path):
    existing = {}
    next_token = None
    while True:
        request = {
            "Path": str(base_path).rstrip("/"),
            "Recursive": True,
            "WithDecryption": False,
        }
        if next_token:
            request["NextToken"] = next_token
        response = _ssm_call(
            "list existing type catalog parameters",
            _ssm().get_parameters_by_path,
            **request,
        )
        for parameter in response.get("Parameters", []):
            name = parameter.get("Name")
            value = parameter.get("Value")
            if isinstance(name, str) and isinstance(value, str):
                existing[name] = value
        next_token = response.get("NextToken")
        if not next_token:
            break
    return existing


def _put_type_catalog_parameters(properties):
    base_path = properties["CatalogBasePath"]
    catalog_parameters = properties.get("CatalogParameters", {})
    if not isinstance(catalog_parameters, dict):
        raise TypeError("CatalogParameters must be a map")

    try:
        _ssm_call(
            "delete legacy type catalog base parameter",
            _ssm().delete_parameter,
            Name=str(base_path).rstrip("/"),
        )
    except Exception as error:
        if _error_code(error) != "ParameterNotFound":
            raise

    existing_parameters = _catalog_existing_parameters(base_path)
    written = []
    for leaf_name, value in sorted(catalog_parameters.items()):
        name = _catalog_parameter_name(base_path, leaf_name)
        value_text = str(value)
        if existing_parameters.get(name) == value_text:
            written.append(name)
            continue
        _ssm_call(
            "put type catalog parameter",
            _ssm().put_parameter,
            Name=name,
            Type="String",
            Value=value_text,
            Overwrite=True,
        )
        written.append(name)
    return written


def _delete_type_catalog_parameters(properties):
    base_path = properties.get("CatalogBasePath")
    if not base_path:
        return {"deletedParameters": 0}

    normalized_base_path = str(base_path).rstrip("/")
    if not normalized_base_path.startswith("/txing/") and normalized_base_path != "/txing":
        raise ValueError(f"Type catalog path must be under /txing: {base_path!r}")

    parameter_names = set()
    next_token = None
    while True:
        request = {
            "Path": normalized_base_path,
            "Recursive": True,
            "WithDecryption": False,
        }
        if next_token:
            request["NextToken"] = next_token
        response = _ssm_call(
            "list type catalog parameters for deletion",
            _ssm().get_parameters_by_path,
            **request,
        )
        for parameter in response.get("Parameters", []):
            name = parameter.get("Name")
            if isinstance(name, str):
                parameter_names.add(name)
        next_token = response.get("NextToken")
        if not next_token:
            break
    parameter_names.add(normalized_base_path)

    deleted = 0
    sorted_names = sorted(parameter_names, reverse=True)
    for offset in range(0, len(sorted_names), SSM_DELETE_BATCH_SIZE):
        batch = sorted_names[offset : offset + SSM_DELETE_BATCH_SIZE]
        response = _ssm_call(
            "delete type catalog parameters",
            _ssm().delete_parameters,
            Names=batch,
        )
        deleted += len(response.get("DeletedParameters", []))
        if offset + SSM_DELETE_BATCH_SIZE < len(sorted_names):
            time.sleep(SSM_DELETE_BATCH_DELAY_SECONDS)
    return {"deletedParameters": deleted, "thingTypeDeletion": "skipped"}


def _ensure_type_catalog(properties):
    thing_type_status = _ensure_thing_type(properties)
    written_parameters = _put_type_catalog_parameters(properties)
    return {
        "thingType": properties["ThingTypeName"],
        "thingTypeStatus": thing_type_status,
        "catalogBasePath": properties["CatalogBasePath"],
        "catalogParameterCount": len(written_parameters),
    }


def _handle_create_or_update(properties):
    cleanup_type = properties.get("CleanupType")
    if cleanup_type == "IotFleetIndexing":
        return _configure_iot_fleet_indexing()
    if cleanup_type == "TypeCatalog":
        return _ensure_type_catalog(properties)
    if cleanup_type == "S3Bucket":
        return {}
    raise ValueError(f"Unsupported CleanupType: {cleanup_type!r}")


def _handle_delete(properties):
    cleanup_type = properties.get("CleanupType")
    if cleanup_type == "S3Bucket":
        return _empty_bucket(properties["BucketName"])
    if cleanup_type == "IotFleetIndexing":
        return {"skipped": True}
    if cleanup_type == "TypeCatalog":
        return _delete_type_catalog_parameters(properties)
    raise ValueError(f"Unsupported CleanupType: {cleanup_type!r}")


def lambda_handler(event, context):
    LOGGER.info("event=%s", json.dumps(event, sort_keys=True))
    properties = event.get("ResourceProperties", {})
    physical_resource_id = properties.get("PhysicalResourceId")
    if properties.get("CleanupType") == "IotFleetIndexing":
        physical_resource_id = physical_resource_id or IOT_FLEET_INDEXING_PHYSICAL_ID
    if properties.get("CleanupType") == "TypeCatalog":
        physical_resource_id = physical_resource_id or (
            "txing-type-catalog-" + properties["ThingTypeName"]
        )
    try:
        data = {}
        if event.get("RequestType") == "Delete":
            if stack_is_deleting(event["StackId"]):
                data = _handle_delete(properties)
            else:
                data = {"skipped": True, "reason": "stack is not deleting"}
        else:
            data = _handle_create_or_update(properties)
        _send_response(
            event,
            context,
            "SUCCESS",
            data,
            physical_resource_id=physical_resource_id,
        )
    except Exception as error:
        LOGGER.exception("custom cleanup failed")
        _send_response(
            event,
            context,
            "FAILED",
            reason=str(error),
            physical_resource_id=physical_resource_id,
        )
