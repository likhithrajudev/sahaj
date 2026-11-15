import * as path from "path";
import { CfnOutput, Duration, Stack, StackProps } from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as rds from "aws-cdk-lib/aws-rds";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Platform } from "aws-cdk-lib/aws-ecr-assets";
import { Construct } from "constructs";

export interface AppStackProps extends StackProps {
  vpc: ec2.Vpc;
  db: rds.DatabaseInstance;
  appSecret: secretsmanager.Secret;
  appSecurityGroup: ec2.SecurityGroup;
  filesBucket: string;
  corsOrigins: string;
  certificateArn?: string;
}

export class AppStack extends Stack {
  constructor(scope: Construct, id: string, props: AppStackProps) {
    super(scope, id, props);
    const { vpc, db, appSecret } = props;

    const cluster = new ecs.Cluster(this, "Cluster", { vpc });
    // Read-only here so CDK adds no rules to it from this stack's side; the one rule we need is created below.
    const tasksSg = ec2.SecurityGroup.fromSecurityGroupId(this, "TasksSg", props.appSecurityGroup.securityGroupId, { mutable: false });
    const task = new ecs.FargateTaskDefinition(this, "Task", {
      cpu: 512,
      memoryLimitMiB: 1024,
      runtimePlatform: { cpuArchitecture: ecs.CpuArchitecture.ARM64, operatingSystemFamily: ecs.OperatingSystemFamily.LINUX },
    });

    const dbSecret = db.secret!;
    const container = task.addContainer("api", {
      image: ecs.ContainerImage.fromAsset(path.join(__dirname, "../../.."), { file: "Dockerfile", platform: Platform.LINUX_ARM64 }),
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: "api", logRetention: logs.RetentionDays.ONE_MONTH }),
      portMappings: [{ containerPort: 8000 }],
      environment: {
        ENVIRONMENT: "production",
        LOG_FORMAT: "json",
        AWS_S3_BUCKET: props.filesBucket,
        AWS_REGION: this.region,
        LEDGER_BACKEND: "postgres",   // consent and audit ledger in RDS: safe with two task sets during blue/green
        TRUST_PROXY_HEADERS: "true",
        AUTO_INGEST: "true",
        TEST_PAGE: "false",
        DEV_LOGIN: "false",
        LANGSMITH_TRACING: "true",
        LANGSMITH_HIDE_IO: "true",
        CORS_ORIGINS: props.corsOrigins,
        DB_NAME: "sahaj",
      },
      secrets: {
        DB_HOST: ecs.Secret.fromSecretsManager(dbSecret, "host"),
        DB_PORT: ecs.Secret.fromSecretsManager(dbSecret, "port"),
        DB_USER: ecs.Secret.fromSecretsManager(dbSecret, "username"),
        DB_PASSWORD: ecs.Secret.fromSecretsManager(dbSecret, "password"),
        ...Object.fromEntries(
          ["SARVAM_API_KEY", "OPENAI_API_KEY", "LANGSMITH_API_KEY", "ADMIN_API_KEY", "GOOGLE_CLIENT_IDS", "FIRECRAWL_API_KEY", "ADMIN_EMAILS", "JWT_SECRET"].map(
            (k) => [k, ecs.Secret.fromSecretsManager(appSecret, k)],
          ),
        ),
      },
    });

    // Files: the existing bucket, including version deletes so consent withdrawal really erases.
    const bucket = s3.Bucket.fromBucketName(this, "Files", props.filesBucket);
    bucket.grantReadWrite(task.taskRole);
    task.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ["s3:ListBucketVersions", "s3:GetObjectVersion", "s3:DeleteObjectVersion"],
      resources: [bucket.bucketArn, bucket.arnForObjects("*")],
    }));

    const albSg = new ec2.SecurityGroup(this, "AlbSg", { vpc, description: "Sahaj load balancer" });
    const alb = new elbv2.ApplicationLoadBalancer(this, "Alb", {
      vpc, internetFacing: true, securityGroup: albSg, idleTimeout: Duration.seconds(300),   // long idle: voice WebSockets
    });
    new ec2.CfnSecurityGroupIngress(this, "AlbToTasks", {
      groupId: props.appSecurityGroup.securityGroupId, sourceSecurityGroupId: albSg.securityGroupId,
      ipProtocol: "tcp", fromPort: 8000, toPort: 8000, description: "Load balancer to API",
    });

    // Blue/green: ECS starts the new version in the idle target group, shifts the listener rule to it, bakes, and
    // rolls back automatically if tasks fail to start or the 5xx alarm fires.
    const targetGroup = (id: string) => new elbv2.ApplicationTargetGroup(this, id, {
      vpc, port: 8000, protocol: elbv2.ApplicationProtocol.HTTP, targetType: elbv2.TargetType.IP,
      healthCheck: { path: "/health", healthyHttpCodes: "200", interval: Duration.seconds(15), healthyThresholdCount: 2 },
      deregistrationDelay: Duration.seconds(30),
    });
    const blue = targetGroup("Blue");
    const green = targetGroup("Green");

    const listener = props.certificateArn
      ? alb.addListener("Https", {
          port: 443,
          certificates: [acm.Certificate.fromCertificateArn(this, "Cert", props.certificateArn)],
          defaultAction: elbv2.ListenerAction.fixedResponse(404),
        })
      : alb.addListener("Http", { port: 80, defaultAction: elbv2.ListenerAction.fixedResponse(404) });
    if (props.certificateArn) alb.addRedirect({ sourcePort: 80, targetPort: 443 });
    const production = new elbv2.ApplicationListenerRule(this, "Production", {
      listener,
      priority: 10,
      conditions: [elbv2.ListenerCondition.pathPatterns(["/*"])],
      action: elbv2.ListenerAction.weightedForward([{ targetGroup: blue, weight: 100 }, { targetGroup: green, weight: 0 }]),
    });

    const errors = new cloudwatch.Alarm(this, "Api5xx", {
      metric: alb.metrics.httpCodeTarget(elbv2.HttpCodeTarget.TARGET_5XX_COUNT, { period: Duration.minutes(1) }),
      threshold: 5,
      evaluationPeriods: 2,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: "Sahaj API 5xx: rolls back a blue/green deployment",
    });

    const service = new ecs.FargateService(this, "Service", {
      cluster,
      taskDefinition: task,
      desiredCount: 1,
      minHealthyPercent: 100,   // blue/green keeps the old task serving until the new one is healthy
      assignPublicIp: true,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      securityGroups: [tasksSg],
      deploymentStrategy: ecs.DeploymentStrategy.BLUE_GREEN,
      bakeTime: Duration.minutes(5),
      circuitBreaker: { rollback: true },
      deploymentAlarms: { alarmNames: [errors.alarmName], behavior: ecs.AlarmBehavior.ROLLBACK_ON_ALARM },
      enableExecuteCommand: true,
      healthCheckGracePeriod: Duration.seconds(90),
    });
    service.loadBalancerTarget({
      containerName: "api",
      containerPort: 8000,
      alternateTarget: new ecs.AlternateTarget("Green", {
        alternateTargetGroup: green,
        productionListener: ecs.ListenerRuleConfiguration.applicationListenerRule(production),
      }),
    }).attachToApplicationTargetGroup(blue);

    // Free HTTPS hostname in front of the ALB (Google sign-in needs an https origin). Nothing is cached.
    const cdn = new cloudfront.Distribution(this, "Cdn", {
      defaultBehavior: {
        origin: new origins.LoadBalancerV2Origin(alb, {
          protocolPolicy: props.certificateArn ? cloudfront.OriginProtocolPolicy.HTTPS_ONLY : cloudfront.OriginProtocolPolicy.HTTP_ONLY,
          readTimeout: Duration.seconds(60),
        }),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
        cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
        originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER,
      },
      priceClass: cloudfront.PriceClass.PRICE_CLASS_200,
    });
    new CfnOutput(this, "Url", { value: `https://${cdn.distributionDomainName}` });
    new CfnOutput(this, "AlbUrl", { value: `${props.certificateArn ? "https" : "http"}://${alb.loadBalancerDnsName}` });
    new CfnOutput(this, "ClusterName", { value: cluster.clusterName });
    new CfnOutput(this, "ServiceName", { value: service.serviceName });
  }
}
