# EKS Assignment - Serverless Platform (EKS on Fargate)

This repository contains AWS Python CDK that deploys:
- Serverless EKS Fargate cluster
- Lambda-backed CustomResource to generate dynamic Helm values
- VPC required Networking
- Security Group
- KMS Encryptions
- Cloudwatch Log Groups
- SSM Parameter Store
- Ingress-nginx Helm Chart

## Overview

- **EKS cluster**, **AWS Fargate** type to be serverless, privately.
- **Fargate profiles** `kube-system`, `default`, and `ingress-nginx` namespaces' resources is scheduled to be serverless.
- **Security group** 
- **VPC** 
- **SSM parameter** `/platform/account/env` (development/staging/production).
- **CustomResource** a Lambda function that reads parameters from the SSM and returns Helm values (`replicaCount`).
- **Ingress-nginx** installed in the cluster using the custom resource for replica count.
- **Unit tests** for the Lambda function using pytest.

All resources are tagged with `Owner=fkocyigit` to point the creator.

## Prerequisites

- An AWS account.
- AWS CLI.
- Python +3.12.
- AWS CDK and relevant packages.

## Setup

```bash
cd eks_assignment/platform
python -m venv .venv
source .venv/bin/activate     
pip install -r requirements.txt
cdk bootstrap aws://YOUR_ACCOUNT_ID/YOUR_REGION
```

1. Deploy the stack:
   ```bash
   cdk synth
   cdk boostrap
   cdk deploy 
   (optional) cdk deploy --parameters Env=production 
   ```
2. After completion you will see outputs:
   - VpcId
   - ClusterName
   - EksSecurityGroupId
   - EksAdminRoleArn
   - ReplicaCount
   - EksSecretsKeyArn
   - LogsEncryptionKeyArn

## Verification

- **CloudFormation console** status `CREATE_COMPLETE`.
- **SSM Parameter Store** verify the parameter `/platform/account/env` exists.
- **EKS console** has an active cluster named `eks-cluster-{account_name}-{self.stack_name}`.
- Use `kubectl` with the required permissions:
  ```bash
  aws eks update-kubeconfig --name <ClusterName> --region <YOUR_REGION> 
  kubectl get pods -n ingress-nginx
  kubectl get svc -n ingress-nginx

  kubectl get deployment ingress-nginx-controller -n ingress-nginx -o jsonpath="{.spec.replicas}" # replica count check
  ```
  The `ClusterName` will be printed as stack outputs.
  The `ingress-nginx` should have replica number depending on the environment.
- **CloudWatch Logs** for Lambda `/aws/lambda/Environment_Function`.
- Run tests with `pytest`

## Cleanup

```bash
cdk destroy
```

## Production Considerations

The following practices were disregarded to comply with the asignment instructions and avoid overengineering. In a real world usecase, I would consider the followings:

**CI/CD**
- GitHub Actions pipeline running tests, vulnerability checks on pushes/PRs, with a deploy strategy based on branch/approval
- ArgoCD or similar tool for environment based deployments and managements

**Security**
- terminationProtection enabled for critical environments
- Lambda reserved concurrency to prevent concurrency exhaustion based on usage predictions
- IAM permission boundaries and SCPs at organization levels
- Kubernetes RBAC for multiple users

**Reliability**
- SQS and SQS DLQ to handle the traffic addition to capture and alert on CustomResource failures
- Lambda X-Ray tracing enabled for distributed observability
- Multi-AZ NAT gateways based on the exposure requirements

**Observability**
- CloudWatch Dashboard for key metrics: Lambda errors, EKS health, ingress request rates, etc
- CloudWatch Alarms with SNS notifications for critical errors and throttles, integratig with Slack-like tools
- Structured logging (JSON) from the Lambda function

**Code Quality and Code Security**
- Pre-commit hooks to formatting and type safety before commits
- CDK integration tests alongside the existing unit tests
- Security and Vulnerability Checks

**Cost & Operations**
- Spot strategy for non-critical workloads 
- Resource tagging policy compliance via AWS Config rules
- Right-sizing CPU/memory requests/utilizations to avoid over-provisioning charges
- Using VPC Endpoints instead of NAT Gateways for large organizations (like 1000s of accounts)

