# CloudFront edge security group update
Provides an AWS Lambda function which is called periodically to synchronize a set of EC2 security groups allowing ingress from [known CloudFront Edge locations](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/LocationsOfEdgeServers.html). These security groups can then be associated to public facing load balancers (ALB/NLB/ELB) or EC2 instances to ensure _only_ traffic originating from CloudFront is accepted.

Lambda optionally supports posting of updates to [Slack](https://slack.com/) via an [incoming webhook](https://api.slack.com/incoming-webhooks).

- [Installing](#installing)
	- [Create security groups](#create-security-groups)
	- [Deploy CloudFormation](#deploy-cloudformation)
	- [Testing](#testing)
- [Building](#building)
- [Future enhancements](#future-enhancements)
- [Reference](#reference)

## Installing
The following steps will get you going with a set of security groups and an automated update process.

### Create security groups
First task, create a collection of security groups:
- At time of writing (April 2018), AWS [list a total](https://ip-ranges.amazonaws.com/ip-ranges.json) of 48 IPv4 CIDR ranges, so at least two security groups will be essential to allow for future CloudFront growth.
- Using three security groups is recommended, especially if you wish to support origin ingress on both `HTTPS` (443) and `HTTP` (80) ports.
- Avoiding support for both HTTPS/HTTP can be achieved by defining CloudFront origins with [`https-only`](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-cloudfront-distribution-customoriginconfig.html#cfn-cloudfront-distribution-customoriginconfig-originprotocolpolicy), thus only `HTTPS` ingress is required for less security group rules.

Once created, note down security group IDs.

### Deploy CloudFormation
The complete application and infrastructure is contained within the CloudFormation stack [`cloudformation/stack.yaml`](cloudformation/stack.yaml), which accepts the following configuration parameters:

Parameter|Description
----|----
`lambdaFunctionName`|Name used for the deployed Lambda function.
`ingressPortList`|When updating security group ingress rules, what ports to open. Defaults to `HTTPS` (443), can also be `HTTP`, or `HTTPS/HTTP`. Allowing both will require double the number of security group rules.
`securityGroupIdList`|A collection of EC2 security group IDs to synchronize with CloudFront edge CIDR ranges as ingress.
`executeSchedule`|Defines how often the Lambda function will be executed, defined as a CloudWatch [schedule expression](https://docs.aws.amazon.com/AmazonCloudWatch/latest/events/ScheduledEvents.html). Defaults to `cron(0 0,6 * * ? *)`, invoking at 12:00am and 6:00am UTC every day.
`slackWebhookURI`|If defined, will push security group updates to a Slack [incoming webhook](https://api.slack.com/incoming-webhooks).
`slackChannel`|Slack channel to publish updates to.
`slackEmoji`|Emoji/icon used for Slack message.
`slackUsername`|Friendly name used for Slack message.

### Testing
With the CloudFormation template successfully deployed, testing can be done by manually invoking the Lambda function. Upon a successful execution, CIDR ingress rules should be populated evenly across the given EC2 security groups.

The Lambda function will then continue to add new CIDR ranges as they become available via the AWS IP range feed plus additionally remove orphaned/invalid CIDR ranges present in security groups.

## Building
The CloudFormation template can be rebuilt via the the [`build/run.sh`](build/run.sh) script.

Build process uses [Lambda smush py](https://github.com/magnetikonline/lambda-smush-py), taking the Lambda function source [`src/index.py`](src/index.py) and generating a compressed version embedded into [`build/template.yaml`](build/template.yaml). This process allows for a Lambda function which can be created entirely via the CloudFormation itself - fitting within the allowed `4KB` code size limit (source function is currently around `7.5KB`).

## Future enhancements
Lambda currently manages IPv4 edge CIDR ranges, additions required to also manage advertised IPv6 range(s). Supporting IPv6 isn't typically an issue though, if origin endpoint(s) (load balancers, etc.) only present IPv4 addresses.

## Reference
- AWS IP ranges: https://ip-ranges.amazonaws.com/ip-ranges.json.
- Lambda smush py: https://github.com/magnetikonline/lambda-smush-py.
