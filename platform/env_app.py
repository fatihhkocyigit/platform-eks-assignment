#!/usr/bin/env python3
import aws_cdk as cdk
from eks.eks_stack import PlatformStack

app = cdk.App()

account       = "ADD_ACCOUNT_ID_HERE"  # ADD_ACCOUNT_ID_HERE
region        = "ADD_REGION_HERE"  # ADD_REGION_HERE
account_name  = "ADD_TEAM_ACCOUNT_NAME_HERE" # ADD_TEAM_ACCOUNT_NAME_HERE
authorized_ip = "ADD_AUTHORIZED_IP_HERE"  # ADD_AUTHORIZED_IP_HERE, WAF IP Whitelist rule can be used

stack = PlatformStack(
    app,
    "PlatformEksStack",
    account_name=account_name,
    authorized_ip=authorized_ip,
    env=cdk.Environment(account=account, region=region),
    description="EKS platform with generşc configuratoin via CustomResource",
)

app.synth()
