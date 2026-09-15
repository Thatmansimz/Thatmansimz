#!/usr/bin/env python3
"""Plan or provision a single paper-only VM. Does not transfer data or start trading."""
import argparse
import json
import re
import shlex
import subprocess


def commands(project, zone, bucket):
    region = zone.rsplit('-', 1)[0]
    sa = f'tajari-paper@{project}.iam.gserviceaccount.com'
    return [
        ['services', 'enable', 'compute.googleapis.com', 'iap.googleapis.com',
         'iam.googleapis.com', 'storage.googleapis.com', 'monitoring.googleapis.com',
         'logging.googleapis.com', 'billingbudgets.googleapis.com'],
        ['compute', 'networks', 'create', 'tajari-paper', '--subnet-mode=custom'],
        ['compute', 'networks', 'subnets', 'create', 'tajari-paper', '--network=tajari-paper',
         f'--region={region}', '--range=10.86.0.0/24'],
        ['compute', 'firewall-rules', 'create', 'tajari-iap-ssh', '--network=tajari-paper',
         '--direction=INGRESS', '--action=ALLOW', '--rules=tcp:22',
         '--source-ranges=35.235.240.0/20', '--target-tags=tajari-paper'],
        ['iam', 'service-accounts', 'create', 'tajari-paper', '--display-name=Tajari paper worker'],
        ['storage', 'buckets', 'create', f'gs://{bucket}', f'--location={region}',
         '--uniform-bucket-level-access', '--public-access-prevention'],
        ['storage', 'buckets', 'add-iam-policy-binding', f'gs://{bucket}',
         f'--member=serviceAccount:{sa}', '--role=roles/storage.objectCreator'],
        ['compute', 'disks', 'create', 'tajari-paper-data', f'--zone={zone}',
         '--size=30GB', '--type=pd-balanced'],
        ['compute', 'instances', 'create', 'tajari-paper-1', f'--zone={zone}',
         '--machine-type=e2-small', '--provisioning-model=STANDARD',
         '--image-family=debian-13', '--image-project=debian-cloud',
         '--boot-disk-size=20GB', '--boot-disk-type=pd-balanced',
         '--disk=name=tajari-paper-data,device-name=tajari-paper-data,mode=rw,boot=no,auto-delete=no',
         '--network=tajari-paper', '--subnet=tajari-paper', '--tags=tajari-paper',
         '--metadata=enable-oslogin=TRUE,block-project-ssh-keys=TRUE,serial-port-enable=FALSE',
         f'--service-account={sa}', '--scopes=cloud-platform',
         '--shielded-secure-boot', '--shielded-vtpm', '--shielded-integrity-monitoring',
         '--maintenance-policy=MIGRATE', '--restart-on-failure', '--deletion-protection',
         '--labels=application=tajari,purpose=internal-paper'],
    ]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', required=True)
    p.add_argument('--account', required=True)
    p.add_argument('--organization', required=True)
    p.add_argument('--zone', default='us-central1-a')
    p.add_argument('--bucket', required=True)
    p.add_argument('--gcloud', default='gcloud')
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    if not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]', args.project): p.error('Invalid project ID')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', args.bucket): p.error('Invalid bucket name')
    if args.zone != 'us-central1-a': p.error('Re-price and review a different zone before changing this plan')
    if not args.organization.isdigit() or '@' not in args.account: p.error('Explicit owner and organization required')
    base = [args.gcloud, f'--project={args.project}', f'--account={args.account}', '--quiet']
    plan = commands(args.project, args.zone, args.bucket)
    for command in plan: print(shlex.join(base + command), flush=True)
    if not args.apply:
        print('PLAN ONLY: no cloud calls, purchases, data transfer or worker startup.')
        return
    def read(command):
        return json.loads(subprocess.check_output(base + command + ['--format=json'], text=True))
    project = read(['projects', 'describe', args.project])
    if project.get('parent') != {'type': 'organization', 'id': args.organization}:
        raise SystemExit('Project does not belong directly to the reviewed company organization')
    if not read(['billing', 'projects', 'describe', args.project]).get('billingEnabled'):
        raise SystemExit('Billing must already be enabled by the account owner')
    # This is deliberately a one-time provisioner, not an overwrite/retry loop.
    # A partial failure leaves resources visible for inspection and continuation.
    for command in plan:
        subprocess.run(base + command, check=True)
    print('Infrastructure created. Worker remains uninstalled and inactive until cutover verification.')


if __name__ == '__main__': main()
