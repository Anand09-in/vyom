"""Vyom health-check Lambda.

Deliberately dependency-free (only stdlib urllib + the boto3 already bundled
in the Lambda Python runtime) — nothing like the torch/sentence-transformers
constraint that ruled out Lambda for the main app; this is a trivial HTTP
GET on a 5-minute schedule. No VPC config: it hits the EC2 instance's
public endpoint over the internet, not the private RDS/ElastiCache path.
"""
import os
import urllib.error
import urllib.request

import boto3

cloudwatch = boto3.client("cloudwatch")
HEALTH_URL = os.environ["HEALTH_URL"]


def handler(event, context):
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as resp:
            up = 1 if resp.status == 200 else 0
    except (urllib.error.URLError, TimeoutError, OSError):
        up = 0

    cloudwatch.put_metric_data(
        Namespace="Vyom/HealthCheck",
        MetricData=[{"MetricName": "Up", "Value": up, "Unit": "None"}],
    )
    return {"up": up}
