import json
import os
import re
import urllib2
import boto3

DRY_RUN = False

AWS_IP_RANGE_URI = 'https://ip-ranges.amazonaws.com/ip-ranges.json'
SERVICE_NAME_CLOUDFRONT = 'CLOUDFRONT'
IP4_CIDR_REGEXP = re.compile(r'^([0-9]{1,3}\.){3}[0-9]{1,3}\/[0-9]{1,3}$')
INGRESS_PROTO = 'tcp'


def handler(event,context):
	# create EC2 boto client
	ec2_client = boto3.client(
		'ec2',
		region_name = AWS_REGION
	)

	# load CloudFront IP range set from public AWS source and transform into CIDR/port tuples
	cloudfront_cidr_port_set = get_cidr_set_merge_port(
		INGRESS_PORT_LIST,
		load_cloudfront_cidr_set()
	)

	# init counters/tracking
	def build_empty_cidr_port_set():
		return {group_id: set() for group_id in SECURITY_GROUP_ID_LIST}

	security_group_remove_cidr_port_set = build_empty_cidr_port_set()
	security_group_add_cidr_port_set = build_empty_cidr_port_set()
	security_group_rule_count = {}

	update_applied = False
	global_cidr_port_set = set()

	if (DRY_RUN):
		print('DRY RUN mode')

	# iterate over security groups - remove orphan IP ranges and build global range set/rule counts
	for security_group_id in SECURITY_GROUP_ID_LIST:
		# query security group for ingress CIDR/port set
		cidr_port_set = get_security_group_cidr_port_set(
			INGRESS_PORT_LIST,
			ec2_client,security_group_id
		)

		# remove any CIDRs in security group not CloudFront related
		orphan_cidr_port_set = cidr_port_set.difference(cloudfront_cidr_port_set)
		if (orphan_cidr_port_set):
			delete_security_group_cidr_port_set(ec2_client,security_group_id,orphan_cidr_port_set)
			update_applied = True

			# note each IP removed from security group
			security_group_remove_cidr_port_set[security_group_id] = orphan_cidr_port_set

		# add defined security group CIDR/port sets a global list and store total rule count
		global_cidr_port_set.update(cidr_port_set)
		security_group_rule_count[security_group_id] = (len(cidr_port_set) - len(orphan_cidr_port_set))

	# iterate over CIDR ranges not currently defined in any security group
	for cidr_port_item in cloudfront_cidr_port_set.difference(global_cidr_port_set):
		# determine security group with current lowest rule count (keep rules balanced between groups)
		security_group_id = min(
			security_group_rule_count,
			key = security_group_rule_count.get
		)

		# add cidr/port to target security group, incr total rule count
		security_group_add_cidr_port_set[security_group_id].add(cidr_port_item)
		security_group_rule_count[security_group_id] += 1

	# now commit security group rule additions
	for security_group_id in SECURITY_GROUP_ID_LIST:
		if (not security_group_add_cidr_port_set[security_group_id]):
			continue

		add_security_group_ingress_cidr_port_set(
			ec2_client,security_group_id,
			security_group_add_cidr_port_set[security_group_id]
		)

		update_applied = True

	# send update report to Slack
	if (update_applied and SLACK_WEBHOOK_URI):
		report_slack_notification(
			SECURITY_GROUP_ID_LIST,
			SLACK_WEBHOOK_URI,SLACK_CHANNEL,SLACK_EMOJI,SLACK_USERNAME,
			security_group_remove_cidr_port_set,
			security_group_add_cidr_port_set
		)

	# finished
	print(
		'Updates applied'
		if update_applied else
		'No work done'
	)

def get_env_var(key,split_char = None):
	# fetch value from environment variables and remove whitespace
	value = os.environ.get(key,'').strip()

	# split value into list if required
	if (split_char):
		return map(
			lambda x: x.strip(),
			value.split(split_char)
		)

	# no split
	return value

def load_cloudfront_cidr_set():
	# fetch data, convert to dict from JSON
	response = urllib2.urlopen(AWS_IP_RANGE_URI)
	data = json.loads(response.read())

	# extract just CloudFront items with valid IP prefix
	def r(accum,item):
		if (
			(item.get('service') == SERVICE_NAME_CLOUDFRONT) and
			(IP4_CIDR_REGEXP.search(item.get('ip_prefix','')))
		):
			# transform, only want the CIDR range from each item
			accum.add(item['ip_prefix'])

		return accum

	return reduce(r,data.get('prefixes',[]),set())

def get_cidr_set_merge_port(port_list,cidr_set):
	def r(accum,item):
		# add CIDR/port combo for each ingress port required
		for port in port_list:
			accum.add((item,port))

		return accum

	return reduce(r,cidr_set,set())

def get_security_group_cidr_port_set(port_list,ec2_client,group_id):
	def r(accum,item):
		# only care about rules with correct proto, single port, and port in our ingress list
		from_port = item['FromPort']

		if (
			(item['IpProtocol'] == INGRESS_PROTO) and
			(from_port == item['ToPort']) and
			(from_port in port_list)
		):
			accum.update({
				(iprange['CidrIp'],from_port)
				for iprange in item['IpRanges']
			})

		return accum

	group_list = ec2_client.describe_security_groups(GroupIds = [group_id])
	return reduce(r,group_list['SecurityGroups'][0]['IpPermissions'],set())

def get_cidr_port_friendly(cidr_port):
	return '{0}:{1}'.format(cidr_port[0],cidr_port[1])

def delete_security_group_cidr_port_set(ec2_client,group_id,cidr_port_set):
	for cidr_port in cidr_port_set:
		print('Deleted: [{0}] from [{1}]'.format(get_cidr_port_friendly(cidr_port),group_id))

	if (not DRY_RUN):
		ec2_client.revoke_security_group_ingress(
			GroupId = group_id,
			IpPermissions = get_ippermissions_from_cidr_port_set(cidr_port_set)
		)

def add_security_group_ingress_cidr_port_set(ec2_client,group_id,cidr_port_set):
	for cidr_port in cidr_port_set:
		print('Added: [{0}] to [{1}]'.format(get_cidr_port_friendly(cidr_port),group_id))

	if (not DRY_RUN):
		ec2_client.authorize_security_group_ingress(
			GroupId = group_id,
			IpPermissions = get_ippermissions_from_cidr_port_set(cidr_port_set)
		)

def get_ippermissions_from_cidr_port_set(cidr_port_set):
	return [
		{
			'FromPort': port_item,
			'IpProtocol': INGRESS_PROTO,
			'IpRanges': [{'CidrIp': cidr_item}],
			'ToPort': port_item
		}
		for cidr_item,port_item in cidr_port_set
	]

def report_slack_notification(
	security_group_id_list,
	webhook_uri,channel,emoji,username,
	remove_cidr_port_set,add_cidr_port_set
):

	def build_message(action_type,security_group_id,cidr_port_set):
		if (not cidr_port_set):
			return ''

		text = '{0} [{1}]:\n'.format(action_type,security_group_id)

		for cidr_port in cidr_port_set:
			text += '- {0}\n'.format(get_cidr_port_friendly(cidr_port))

		return text + '\n'

	def code_block(text):
		return ('\n```{0}```\n'.format(text.strip('\n'))) if (text) else ''

	# create security group rule modification message sections
	removed_message = ''
	added_message = ''
	for security_group_id in security_group_id_list:
		removed_message += build_message(
			'Removed from',
			security_group_id,remove_cidr_port_set[security_group_id]
		)

		added_message += build_message(
			'Added to',
			security_group_id,add_cidr_port_set[security_group_id]
		)

	# build payload
	payload = {
		'text': (
			'The following CIDR range updates have been applied to CloudFront associated security groups:' +
			code_block(removed_message) +
			code_block(added_message)
		)
	}

	if (channel):
		payload['channel'] = '#{0}'.format(channel)

	if (emoji):
		payload['icon_emoji'] = ':{0}:'.format(emoji)

	if (username):
		payload['username'] = username

	# send message
	request = urllib2.Request(
		webhook_uri,
		headers = {'Content-Type': 'application/json'},
		data = json.dumps(payload)
	)

	urllib2.urlopen(request)


# fetch environment constants
# note: no bounds checks here, values assumed fit for purpose
AWS_REGION = get_env_var('AWS_REGION')

INGRESS_PORT_LIST = map(int,get_env_var('INGRESS_PORT_LIST',',')) # as integers
SECURITY_GROUP_ID_LIST = get_env_var('SECURITY_GROUP_ID_LIST',',')

SLACK_WEBHOOK_URI = get_env_var('SLACK_WEBHOOK_URI')
SLACK_CHANNEL = get_env_var('SLACK_CHANNEL')
SLACK_EMOJI = get_env_var('SLACK_EMOJI')
SLACK_USERNAME = get_env_var('SLACK_USERNAME')
