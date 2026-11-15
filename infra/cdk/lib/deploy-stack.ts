import { CfnOutput, Stack, StackProps } from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import { Construct } from "constructs";

export interface DeployStackProps extends StackProps {
  repository: string;
  branch: string;
}

// GitHub Actions deploys with short-lived OIDC credentials; the role can only assume the CDK bootstrap roles.
export class DeployStack extends Stack {
  constructor(scope: Construct, id: string, props: DeployStackProps) {
    super(scope, id, props);

    const provider = new iam.OpenIdConnectProvider(this, "GitHub", {
      url: "https://token.actions.githubusercontent.com",
      clientIds: ["sts.amazonaws.com"],
    });

    const role = new iam.Role(this, "GitHubDeploy", {
      roleName: "sahaj-github-deploy",
      assumedBy: new iam.WebIdentityPrincipal(provider.openIdConnectProviderArn, {
        StringEquals: {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": `repo:${props.repository}:ref:refs/heads/${props.branch}`,
        },
      }),
    });
    role.addToPolicy(new iam.PolicyStatement({
      actions: ["sts:AssumeRole"],
      resources: [`arn:aws:iam::${this.account}:role/cdk-hnb659fds-*-${this.account}-${this.region}`],
    }));

    new CfnOutput(this, "RoleArn", { value: role.roleArn });
  }
}
