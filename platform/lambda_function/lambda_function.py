import json
import logging
from typing import Any, Dict
import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_environment_from_ssm(ssm_client: Any, parameter_name: str) -> str:
    response = ssm_client.get_parameter(
        Name=parameter_name,
        WithDecryption=False,
    )
    return response["Parameter"]["Value"]


def generate_helm_values(env: str) -> Dict[str, Any]:
    env_lower = env.strip().lower()

    replica_map = {
        "development": 1,
        "staging": 2,
        "production": 2,
    }

    if env_lower not in replica_map:
        raise ValueError(
            f"Unknown environment: '{env}'. "
            f"Expected one of: {list(replica_map.keys())}"
        )

    replica_count = replica_map[env_lower]
    logger.info(f"Environment '{env}' mapped to {replica_count} replica(s)")

    return {
        "controller": {
            "replicaCount": replica_count,
        },
    }

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    logger.info(f"Received event: {json.dumps(event)}")

    request_type = event.get("RequestType")

    if request_type in ("Create", "Update"):
        props = event.get("ResourceProperties", {})
        param_name = props.get(
            "SsmParameterName",
            "/platform/account/env",
        )

        logger.info(f"Using SSM parameter: {param_name}")

        ssm_client = boto3.client("ssm")
        env = get_environment_from_ssm(ssm_client, param_name)

        helm_values = generate_helm_values(env)
        replica_count = helm_values["controller"]["replicaCount"]

        return {
            "PhysicalResourceId": "helm-values",
            "Data": {
                "replicaCount": str(replica_count),
                "helmValuesJson": json.dumps(helm_values),
            },
        }

    elif request_type == "Delete":
        logger.info("Delete request received, nothing to clean up")
        return {"PhysicalResourceId": event.get("PhysicalResourceId", "helm-values")}

    else:
        error_msg = f"Unexpected RequestType: {request_type}"
        raise ValueError(error_msg)
