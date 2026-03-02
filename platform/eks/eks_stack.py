from constructs import Construct
import aws_cdk as cdk
from aws_cdk import aws_eks as eks
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_ssm as ssm
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from aws_cdk import custom_resources as cr
from aws_cdk.lambda_layer_kubectl_v34 import KubectlV34Layer

class PlatformStack(cdk.Stack):

    def __init__(self, scope: Construct, construct_id: str, account_name: str, authorized_ip: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ------------------------------------------------------------------
        # Environment parameter
        # ------------------------------------------------------------------
        env_param = cdk.CfnParameter(
            self,
            "EnvParam",
            type="String",
            allowed_values=["development", "staging", "production"],
            default="development",
            description="Environment values stored in SSM to control replica count",
        )

        static_tags = {
            "Project": "EKS-Stack",
            "ManagedBy": "CDK",
            "Owner": "fkocyigit",
            "CostCenter": "PlatformEngineering",
            "AccountName": account_name,
        }

        for key, value in static_tags.items():
            cdk.Tags.of(self).add(key, value)

        cdk.Tags.of(self).add(
            "Environment",
            env_param.value_as_string,
            exclude_resource_types=["Custom::AWSCDK-EKS-FargateProfile"],
        )

        # TODO terminationProtection can be implemented for production and critical resources

        # ------------------------------------------------------------------
        # SSM Parameter
        # ------------------------------------------------------------------
        ssm_param = ssm.StringParameter(
            self,
            "EnvParameter",
            parameter_name=f"/platform/account/env", # {account_name} can be used for multi account strategy to distinguish per account
            string_value=env_param.value_as_string,
        )

        # ------------------------------------------------------------------
        # VPC: Private and Public subnets with NAT and VPC Flow Logs
        # ------------------------------------------------------------------
        vpc = ec2.Vpc(
            self,
            "EksVpc",
            vpc_name=f"eks-vpc-{account_name}-{self.stack_name}",
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PUBLIC,
                    name=f"eks-public-{account_name}-{self.stack_name}",
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    name=f"eks-private-{account_name}-{self.stack_name}",
                    cidr_mask=24,
                ),
            ],
        )

        vpc_flow_log_group = logs.LogGroup(
            self,
            "VpcFlowLogGroup",
            log_group_name=f"/{account_name}/eks/vpc/flow-logs/{self.stack_name}",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        vpc_flow_log = vpc.add_flow_log(
            "VpcFlowLog",
            destination=ec2.FlowLogDestination.to_cloud_watch_logs(vpc_flow_log_group),
        )

        # ------------------------------------------------------------------
        # Security Group: Allow local IP tı access cluster and intra cluster communication
        # ------------------------------------------------------------------
        eks_sg = ec2.SecurityGroup(
            self,
            "EksSG",
            vpc=vpc,
            security_group_name=f"eks-sg-{account_name}-{self.stack_name}",
            description=f"{account_name} EKS cluster security group",
            allow_all_outbound=True,
        )

        eks_sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(f"{authorized_ip}/32"),
            connection=ec2.Port.tcp(80),
            description=f"Allow HTTP from IP: {authorized_ip}",
        )

        eks_sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(f"{authorized_ip}/32"),
            connection=ec2.Port.tcp(443),
            description=f"Allow HTTPS from IP: {authorized_ip}",
        )

        eks_sg.add_ingress_rule(
            peer=eks_sg,
            connection=ec2.Port.all_traffic(),
            description="Allow intra cluster communicatoin",
        )

        # ------------------------------------------------------------------
        # IAM — EKS Cluster Role
        # ------------------------------------------------------------------
        cluster_role = iam.Role(
            self,
            "EksClusterRole",
            role_name=f"eks-cluster-role-{account_name}-{self.stack_name}",
            assumed_by=iam.ServicePrincipal("eks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonEKSClusterPolicy"
                ),
            ],
            description=f"{account_name} EKS role",
        )

        # ------------------------------------------------------------------
        # KMS Encryption for EKS and CloudWatch Logs
        # ------------------------------------------------------------------
        secrets_key = kms.Key(
            self,
            "EksSecretsKey",
            description=f"{account_name} EKS Kubernetes secrets encryption key",
            enable_key_rotation=True,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        kms.Alias(
            self,
            "EksSecretsKeyAlias",
            alias_name=f"alias/eks-secrets-key-{account_name}-{self.stack_name}",
            target_key=secrets_key,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        logs_key = kms.Key(
            self,
            "LogsEncryptionKey",
            description=f"{account_name} EKS CloudWatch Logs encryption key",
            enable_key_rotation=True,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        kms.Alias(
            self,
            "LogsEncryptionKeyAlias",
            alias_name=f"alias/eks-logs-key-{account_name}-{self.stack_name}",
            target_key=logs_key,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # ------------------------------------------------------------------
        # EKS Fargate Cluster
        # ------------------------------------------------------------------
        cluster = eks.Cluster(
            self,
            "PlatformCluster",
            cluster_name=f"eks-cluster-{account_name}-{self.stack_name}",
            role=cluster_role,
            version=eks.KubernetesVersion.V1_34,
            vpc=vpc,
            vpc_subnets=[
                ec2.SubnetSelection(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                ),
            ],
            security_group=eks_sg,
            default_capacity=0,
            kubectl_layer=KubectlV34Layer(self, "KubectlLayer"),
            authentication_mode=eks.AuthenticationMode.API_AND_CONFIG_MAP,
            secrets_encryption_key=secrets_key,
            
            # Control plane logging for audit
            cluster_logging=[
                eks.ClusterLoggingTypes.API,
                eks.ClusterLoggingTypes.AUDIT,
                eks.ClusterLoggingTypes.AUTHENTICATOR,
                eks.ClusterLoggingTypes.CONTROLLER_MANAGER,
                eks.ClusterLoggingTypes.SCHEDULER,
            ],
        )

        # ------------------------------------------------------------------
        # EKS Admin Role
        # ------------------------------------------------------------------
        eks_admin_role = iam.Role(
            self,
            "EksAdminRole",
            role_name=f"eks-admin-role-{account_name}-{self.stack_name}",
            assumed_by=iam.AccountPrincipal(self.account),
            description=f"{account_name} EKS admin role to be assumed for local access ",
        )

        cluster.grant_access(
            "ClusterAdminAccess",
            principal=eks_admin_role.role_arn,
            access_policies=[
                eks.AccessPolicy.from_access_policy_name(
                    "AmazonEKSClusterAdminPolicy",
                    access_scope_type=eks.AccessScopeType.CLUSTER,
                ),
            ],
        )

        eks_admin_role.add_to_policy(
            iam.PolicyStatement(
                sid="EksLocalAccess",
                actions=[
                    "eks:DescribeCluster",
                    "eks:ListFargateProfiles",
                    "eks:DescribeFargateProfile",
                ],
                resources=[cluster.cluster_arn],
            )
        )

        # ------------------------------------------------------------------
        # Fargate IAM Role
        # ------------------------------------------------------------------
        fargate_role = iam.Role(
            self,
            "EKSFargateRole",
            role_name=f"eks-fargate-role-{account_name}-{self.stack_name}",
            assumed_by=iam.ServicePrincipal("eks-fargate-pods.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonEKSFargatePodExecutionRolePolicy"
                ),
            ],
            description=f"{account_name} EKS Fargate role",
        )

        # ------------------------------------------------------------------
        # Fargate Profiles
        # ------------------------------------------------------------------
        cluster.add_fargate_profile(
            "KubeSystemProfile",
            fargate_profile_name="kube-system",
            pod_execution_role=fargate_role,
            selectors=[eks.Selector(namespace="kube-system", labels={"k8s-app": "kube-dns"})],
        )

        cluster.add_fargate_profile(
            "DefaultProfile",
            fargate_profile_name="default",
            pod_execution_role=fargate_role,
            selectors=[eks.Selector(namespace="default")],
        )

        cluster.add_fargate_profile(
            "IngressNginxProfile",
            fargate_profile_name="ingress-nginx",
            pod_execution_role=fargate_role,
            selectors=[eks.Selector(namespace="ingress-nginx")],
        )

        # ------------------------------------------------------------------
        # Lambda Log Group
        # ------------------------------------------------------------------
        helm_values_log_group = logs.LogGroup(
            self,
            "LambdaLogGroup",
            log_group_name=f"/{account_name}/lambda/helm-values/{self.stack_name}",
            retention=logs.RetentionDays.ONE_WEEK,
            encryption_key=logs_key,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # ------------------------------------------------------------------
        # Lambda for CustomResource
        # ------------------------------------------------------------------
        lambda_fn = _lambda.Function(
            self,
            "HelmValuesGenerator",
            function_name=f"helmValuesGenerator-{account_name}-{self.stack_name}",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="lambda_function.lambda_handler",
            code=_lambda.Code.from_asset("lambda_function"),
            timeout=cdk.Duration.seconds(30),
            memory_size=128,
            log_group=helm_values_log_group,
            environment={
                "SSM_PARAMETER_NAME": ssm_param.parameter_name,
            },
            description=f"Generates Helm values from SSM environment parameter",
        )


        lambda_fn.add_to_role_policy(
            iam.PolicyStatement(
                sid="SsmGetEnvParameter",
                actions=["ssm:GetParameter"],
                resources=[ssm_param.parameter_arn],
            )
        )

        # ------------------------------------------------------------------
        # Lambda CR Log Group
        # ------------------------------------------------------------------
        helm_values_generator_log_group = logs.LogGroup(
            self,
            "HelmValuesGeneratorLogGroup",
            log_group_name=f"/{account_name}/lambda/cr-provider/{self.stack_name}",
            retention=logs.RetentionDays.ONE_WEEK,
            encryption_key=logs_key,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # ------------------------------------------------------------------
        # CustomResource backed by Lambda
        # ------------------------------------------------------------------
        provider = cr.Provider(
            self,
            "HelmValuesGeneratorProvider",
            on_event_handler=lambda_fn,
            log_group=helm_values_generator_log_group,
        )

        custom_resource = cdk.CustomResource(
            self,
            "HelmValuesGeneratorResource",
            service_token=provider.service_token,
            properties={
                "SsmParameterName": ssm_param.parameter_name,
                "EnvValue": env_param.value_as_string,
            },
        )

        custom_resource.node.add_dependency(ssm_param)

        # ------------------------------------------------------------------
        # KMS Logs Key Resource Policy
        # ------------------------------------------------------------------
        logs_key.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowCloudWatchLogs",
                principals=[
                    iam.ServicePrincipal(f"logs.{self.region}.amazonaws.com")
                ],
                actions=[
                    "kms:Encrypt",
                    "kms:Decrypt",
                    "kms:ReEncrypt*",
                    "kms:GenerateDataKey*",
                    "kms:CreateGrant",
                    "kms:DescribeKey",
                ],
                resources=["*"],
                conditions={
                    "ArnLike": {
                        "kms:EncryptionContext:aws:logs:arn": [
                            f"arn:aws:logs:{self.region}:{self.account}:log-group:/{account_name}/lambda/helm-values/{self.stack_name}",
                            f"arn:aws:logs:{self.region}:{self.account}:log-group:/{account_name}/lambda/cr-provider/{self.stack_name}",
                            f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/eks/eks-cluster-{account_name}-{self.stack_name}/cluster",
                            vpc_flow_log.log_group.log_group_arn,
                        ]
                    }
                },
            )
        )

        # ReplicaCount CDK Token from CustomResource
        replica_count = custom_resource.get_att_string("replicaCount")


        # ------------------------------------------------------------------
        # Ingress-nginx Helm Chart
        # ------------------------------------------------------------------
        chart = cluster.add_helm_chart(
            "IngressNginx",
            chart="ingress-nginx",
            repository="https://kubernetes.github.io/ingress-nginx",
            namespace="ingress-nginx",
            release="ingress-nginx",
            create_namespace=True,
            values={
                "controller": {
                    "replicaCount": cdk.Token.as_number(replica_count),
                    "service": {
                        "type": "NodePort", # CLB/NLB not supported on Fargate. ALB-IP target can be implemented for production and external access usecases.
                    },
                },
            },
        )

        chart.node.add_dependency(custom_resource)

        # ------------------------------------------------------------------
        # Outputs
        # ------------------------------------------------------------------
        cdk.CfnOutput(
            self,
            "EksAdminRoleArn",
            value=eks_admin_role.role_arn,
            description="Assume role to access the EKS from local",
        )

        cdk.CfnOutput(self, "VpcId", value=vpc.vpc_id)
        
        cdk.CfnOutput(self, "ClusterName", value=cluster.cluster_name)
        
        cdk.CfnOutput(self, "EksSecurityGroupId", value=eks_sg.security_group_id)
        
        cdk.CfnOutput(
            self,
            "ReplicaCount",
            value=replica_count,
            description="controller.replicaCount from CustomResource",
        )

        cdk.CfnOutput(
            self,
            "EksSecretsKeyArn",
            value=secrets_key.key_arn,
            description="KMS key ARN for EKS encryption",
        )

        cdk.CfnOutput(
            self,
            "LogsEncryptionKeyArn",
            value=logs_key.key_arn,
            description="KMS key ARN for CloudWatch Logs encryption",
        )
