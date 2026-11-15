import { Duration, RemovalPolicy, Stack, StackProps } from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as rds from "aws-cdk-lib/aws-rds";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";

// Stateful resources live here, apart from the app, with termination protection.
export class DataStack extends Stack {
  readonly vpc: ec2.Vpc;
  readonly db: rds.DatabaseInstance;
  readonly appSecret: secretsmanager.Secret;
  readonly appSecurityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: StackProps) {
    super(scope, id, props);

    // No NAT gateway: tasks run in public subnets with a public IP; the database stays in isolated subnets.
    this.vpc = new ec2.Vpc(this, "Vpc", {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        { name: "public", subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: "data", subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
    });

    this.db = new rds.DatabaseInstance(this, "Postgres", {
      engine: rds.DatabaseInstanceEngine.postgres({ version: rds.PostgresEngineVersion.VER_16 }),
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO),
      vpc: this.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      credentials: rds.Credentials.fromGeneratedSecret("sahaj_admin", { secretName: "sahaj/db" }),
      databaseName: "sahaj",
      allocatedStorage: 20,
      maxAllocatedStorage: 100,
      storageEncrypted: true,
      backupRetention: Duration.days(7),
      deletionProtection: true,
      removalPolicy: RemovalPolicy.SNAPSHOT,
      publiclyAccessible: false,
      parameters: { "rds.force_ssl": "1" },
    });

    // The API tasks' security group lives here so the database rule stays in this stack (no cycle).
    this.appSecurityGroup = new ec2.SecurityGroup(this, "AppTasks", { vpc: this.vpc, description: "Sahaj API tasks" });
    this.db.connections.allowDefaultPortFrom(this.appSecurityGroup, "API to Postgres");

    // API keys are filled in after deploy by scripts/push-secrets.sh; the JWT secret is generated here.
    this.appSecret = new secretsmanager.Secret(this, "AppSecret", {
      secretName: "sahaj/app",
      generateSecretString: {
        secretStringTemplate: JSON.stringify({
          SARVAM_API_KEY: "", OPENAI_API_KEY: "", LANGSMITH_API_KEY: "", ADMIN_API_KEY: "", GOOGLE_CLIENT_IDS: "",
        }),
        generateStringKey: "JWT_SECRET",
        passwordLength: 64,
        excludePunctuation: true,
      },
    });
  }
}
