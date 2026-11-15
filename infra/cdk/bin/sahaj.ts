import { App } from "aws-cdk-lib";
import { AppStack } from "../lib/app-stack";
import { DataStack } from "../lib/data-stack";
import { DeployStack } from "../lib/deploy-stack";

const app = new App();
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: app.node.tryGetContext("region") };

const data = new DataStack(app, "SahajData", { env, terminationProtection: true });
new AppStack(app, "SahajApp", {
  env,
  vpc: data.vpc,
  db: data.db,
  appSecret: data.appSecret,
  appSecurityGroup: data.appSecurityGroup,
  filesBucket: app.node.tryGetContext("filesBucket"),
  corsOrigins: app.node.tryGetContext("corsOrigins"),
  certificateArn: app.node.tryGetContext("certificateArn") || undefined,
});

// Opt-in: some AWS organisations forbid creating the GitHub OIDC provider.
if (app.node.tryGetContext("githubOidc") === "true") new DeployStack(app, "SahajDeploy", {
  env,
  repository: app.node.tryGetContext("githubRepository"),
  branch: "main",
});
