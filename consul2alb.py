#!/usr/bin/env python2
"""
Keeps an ALB target group in sync with a Consul service.
"""

import boto3
import consul
import datetime
import os

SERVICE_NAME=os.environ['CONSUL2ALB_SERVICE_NAME']
TARGET_GROUP_ARN=os.environ['CONSUL2ALB_TARGET_GROUP_ARN']

cul = consul.Consul()
elb = boto3.client('elbv2')

def get_alb_target_from_health(health):
    target = health['Target']
    return (target['Id'], target['Port'])

def is_alb_target_active(health):
    state = health['TargetHealth']['State']
    return state != 'draining'

def get_alb_targets(target_group_arn):
    response = elb.describe_target_health(
        TargetGroupArn=target_group_arn,
    )
    return [
        get_alb_target_from_health(health)
        for health in response['TargetHealthDescriptions']
        if is_alb_target_active(health)
    ]

def is_consul_service_healthy(service):
    return all(
        c['Status'] == 'passing'
        for c in service['Checks']
    )

# Blocks if `index` is provided!
def get_consul_services(service_name, index):
    index, services = cul.health.service(service_name, index=index)
    return (
        index,
        [
            (s['Node']['Node'], s['Service']['Port'])
            for s in services
            if is_consul_service_healthy(s)
        ]
    )

def target_states(service_name, target_group_arn):
    index = None
    while True:
        index, consul_services = get_consul_services(service_name, index)
        alb_targets = get_alb_targets(target_group_arn)
        yield {
            'before': frozenset(alb_targets),
            'after': frozenset(consul_services),
        }

def diff_state(before, after):
    return {
        'add': after - before,
        'remove': before - after,
    }

def consume(iterator):
    for i in iterator:
        pass

def _alb_target_list(iterator):
    return [
        {
            'Id': id,
            'Port': port,
        }
        for id, port in iterator
    ]

def print_diff(diff_add, diff_remove):
    timestamp = datetime.datetime.utcnow().isoformat()
    if diff_add:
        for id, port in diff_add:
            print('{} + {}/{}'.format(timestamp, id, port))
    if diff_remove:
        for id, port in diff_remove:
            print('{} - {}/{}'.format(timestamp, id, port))

def apply_alb_diff(target_group_arn, diff):
    diff_add = diff['add']
    diff_remove = diff['remove']
    response_add = None
    response_remove = None
    if diff_add:
        response_add = elb.register_targets(
            TargetGroupArn=target_group_arn,
            Targets=_alb_target_list(diff_add)
        )
    if diff_remove:
        response_remove = elb.deregister_targets(
            TargetGroupArn=target_group_arn,
            Targets=_alb_target_list(diff_remove)
        )
    print_diff(diff_add, diff_remove)
    return {
        'add': response_add,
        'remove': response_remove,
    }

def main():
    state_stream = target_states(SERVICE_NAME, TARGET_GROUP_ARN)
    diff_stream = (diff_state(**s) for s in state_stream)
    result_stream = (apply_alb_diff(TARGET_GROUP_ARN, diff) for diff in diff_stream)
    consume(result_stream)

if __name__ == '__main__':
    main()
